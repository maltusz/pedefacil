from .models import DeliveryRange
import googlemaps
from django.conf import settings
import logging
import requests
from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger(__name__)

def calculate_distance(estabelecimento, client_address):
    logger.debug(f"Calculando distância para estabelecimento: {estabelecimento}, cliente: {client_address}")

    # Inicializa o cliente Google Maps para geocodificação
    try:
        gmaps = googlemaps.Client(key=settings.GOOGLE_MAPS_API_KEY)
    except ValueError as e:
        logger.error(f"Erro ao inicializar cliente Google Maps: {str(e)}")
        raise ImproperlyConfigured("Chave da API do Google Maps inválida ou não configurada.")

    # Usa latitude e longitude do estabelecimento, se disponíveis
    if estabelecimento.estabelecimento_latitude and estabelecimento.estabelecimento_longitude:
        restaurant_geo = {'lat': estabelecimento.estabelecimento_latitude, 'lng': estabelecimento.estabelecimento_longitude}
    else:
        endereco_estabelecimento = (
            f"{estabelecimento.endereco}, {estabelecimento.numero}, "
            f"{estabelecimento.bairro}, {estabelecimento.cidade} - "
            f"{estabelecimento.estado}, Brasil"
        )
        try:
            restaurant_results = gmaps.geocode(endereco_estabelecimento)
            if not restaurant_results:
                raise ValueError("Endereço do estabelecimento não encontrado")
            restaurant_geo = restaurant_results[0]['geometry']['location']
            logger.debug(f"Geocodificação do estabelecimento: {restaurant_geo}")
        except Exception as e:
            logger.error(f"Erro ao geocodificar endereço do estabelecimento: {str(e)}")
            raise ValueError("Não foi possível geocodificar o endereço do estabelecimento")

    try:
        # Geocodifica o endereço do cliente
        logger.debug(f"Endereço do cliente enviado para geocodificação: {client_address}")
        geocoding_results = gmaps.geocode(client_address)
        if not geocoding_results:
            raise ValueError("Endereço do cliente não encontrado")

        # Loga todos os resultados
        for i, result in enumerate(geocoding_results):
            logger.debug(
                f"Resultado {i}: {result['formatted_address']}, "
                f"location_type: {result.get('geometry', {}).get('location_type')}, "
                f"partial_match: {result.get('partial_match', False)}"
            )

        # Escolhe o resultado mais preciso (priorizando ROOFTOP)
        best_result = None
        for result in geocoding_results:
            if (result.get('geometry', {}).get('location_type') == 'ROOFTOP' and
                not result.get('partial_match', False)):
                best_result = result
                break
        if not best_result:
            best_result = geocoding_results[0]
            if (best_result.get('partial_match', False) or
                best_result.get('geometry', {}).get('location_type') in ['RANGE_INTERPOLATED', 'APPROXIMATE']):
                logger.warning(
                    f"Geocodificação imprecisa: {best_result['formatted_address']}, "
                    f"location_type: {best_result.get('geometry', {}).get('location_type')}"
                )

        client_geo = best_result['geometry']['location']
        logger.debug(f"Coordenadas do Cliente: lat={client_geo['lat']}, lng={client_geo['lng']}")
        logger.debug(f"Tipo de localização do cliente: {best_result.get('geometry', {}).get('location_type')}")
        logger.debug(f"Endereço formatado retornado: {best_result['formatted_address']}")

        # Monta a requisição para a Routes API
        routes_url = "https://routes.googleapis.com/directions/v2:computeRoutes"
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": settings.GOOGLE_MAPS_API_KEY,
            "X-Goog-FieldMask": "routes.distanceMeters"
        }
        payload = {
            "origin": {
                "location": {
                    "latLng": {
                        "latitude": restaurant_geo['lat'],
                        "longitude": restaurant_geo['lng']
                    }
                }
            },
            "destination": {
                "location": {
                    "latLng": {
                        "latitude": client_geo['lat'],
                        "longitude": client_geo['lng']
                    }
                }
            },
            "travelMode": "DRIVE",
            "routingPreference": "TRAFFIC_AWARE",
            "computeAlternativeRoutes": False,
            "units": "METRIC",
            "languageCode": "pt-BR"
        }

        # Faz a requisição à Routes API
        logger.debug(f"Enviando requisição para Routes API: {payload}")
        response = requests.post(routes_url, json=payload, headers=headers)
        response.raise_for_status()  # Levanta exceção para erros HTTP
        routes_data = response.json()

        logger.debug(f"Resposta da Routes API: {routes_data}")

        # Extrai a distância
        if not routes_data.get("routes"):
            raise ValueError("Nenhuma rota encontrada entre os pontos fornecidos")
        
        distance_meters = routes_data["routes"][0]["distanceMeters"]
        distance_km = distance_meters / 1000
        logger.debug(f"Distância calculada: {distance_km} km")

        return distance_km

    except requests.exceptions.RequestException as e:
        logger.error(f"Erro ao chamar Routes API: {str(e)}")
        raise ValueError(f"Erro ao calcular distância: {str(e)}")
    except Exception as e:
        logger.error(f"Erro ao calcular distância: {str(e)}")
        raise

def get_delivery_fee(estabelecimento, distance_km):
    logger.debug(f"Buscando taxa de entrega para estabelecimento: {estabelecimento}, distância: {distance_km}")
    try:
        delivery_range = DeliveryRange.objects.filter(
            estabelecimento=estabelecimento,
            min_distance__lte=distance_km,
            max_distance__gt=distance_km
        ).first()
        
        if delivery_range:
            logger.debug(f"Taxa encontrada: {delivery_range.delivery_fee}")
            return delivery_range.delivery_fee
        else:
            logger.error("Nenhuma faixa de entrega encontrada.")
            raise Exception("Nenhuma faixa de entrega encontrada para a distância fornecida.")
    except Exception as e:
        logger.error(f"Erro ao buscar taxa de entrega: {str(e)}")
        raise