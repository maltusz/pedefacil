from decimal import Decimal
from django.db import transaction
import logging
import json
from decouple import config
import requests
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse
from django.db.models import Prefetch
from delivery.models import Produto, ProdutoForm, Acrescimo, Cliente, Pedido, ItensPedido, TipoProduto, TamanhoProdutoFormSet, AcrescimoForm, TamanhoProduto, FormasDePagamento, Estabelecimento, Promocao
from weasyprint import HTML
from django.template.loader import render_to_string
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django.core.serializers.json import DjangoJSONEncoder
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework import status
from rest_framework.views import APIView
from .serializers import ProdutoSerializer, TipoProdutoSerializer, TamanhoProdutoSerializer, AcrescimoSerializer, PedidoSerializer, EstabelecimentoUpdateSerializer, DeliveryFeeRequestSerializer, DeliveryFeeResponseSerializer, PromocaoSerializer

from .utils import calculate_distance, get_delivery_fee

logger = logging.getLogger(__name__)

class DeliveryFeeView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = DeliveryFeeRequestSerializer(data=request.data)
        if serializer.is_valid():
            # O serializer já retorna o objeto Estabelecimento, não o ID
            estabelecimento = serializer.validated_data['estabelecimento_id']
            client_address_data = serializer.validated_data['client_address']
            
            client_address = (
                f"{client_address_data['rua']}, "
                f"{client_address_data['numero']} {client_address_data.get('complemento', '')}, "
                f"{client_address_data.get('bairro', '')}, "
                f"{client_address_data.get('cidade', '')}, "
                f"{client_address_data.get('estado', '')}, "
                f"{client_address_data.get('cep', '')}, Brasil"
            ).replace(", ,", ",").strip(", ")

            try:
                # Calcular distância
                distance_km = calculate_distance(estabelecimento, client_address)
                
                # Obter taxa de entrega
                delivery_fee = get_delivery_fee(estabelecimento, distance_km)
                
                response_data = {
                    'distance_km': round(distance_km, 2),
                    'delivery_fee': delivery_fee
                }
                return Response(
                    DeliveryFeeResponseSerializer(response_data).data,
                    status=status.HTTP_200_OK
                )
            except Exception as e:
                return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

## View para renderizar a landing page da empresa
def landing_page(request):
    return render(request, 'delivery/landing_page.html')

# View de interação do chatbot **Tenho de pensar em algum tipo de autenticação
def chatbot(request, estab_url):
    print("Chatbot view chamada")

## Views da parte do cliente no sistema ####

def send_order_notification(pedido):
    """
    Envia notificação WebSocket para o grupo específico do estabelecimento.
    """
    try:
        logger.info("Enviando notificação para novo pedido: %s", pedido.id)
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f'orders_{pedido.pedido_estabelecimento.id}',  # Grupo dinâmico
            {
                'type': 'new_order',
                'order': {
                    'id': pedido.id,
                    'estabelecimento': pedido.pedido_estabelecimento.estabelecimento_nome,
                    'cliente': pedido.pedido_cliente.cliente_nome,
                    'valor_total': float(pedido.pedido_valor_total),
                    'status': pedido.pedido_status,
                    'data': str(pedido.pedido_data),
                    'forma_pagamento': pedido.pedido_forma_pagamento.forma_pagamento_nome,
                    'observacao': pedido.pedido_observacao or '',
                }
            }
        )
        logger.info("Notificação enviada para pedido: %s no grupo orders_%s", pedido.id, pedido.pedido_estabelecimento.id)
    except Exception as e:
        logger.error("Erro ao enviar notificação para pedido %s: %s", pedido.id, str(e))
        # Não interrompe a resposta, apenas loga o erro

@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def menu_delivery(request, estab_url):
    try:
        # Busca o estabelecimento
        estabelecimento = Estabelecimento.objects.filter(
            estabelecimento_url=estab_url,
            estabelecimento_aberto=True
        ).values(
            'id',
            'estabelecimento_nome',
            'estabelecimento_logo',
            'estabelecimento_prazo_entrega',
            'estabelecimento_chave_pix',
            'estabelecimento_url',
            'estabelecimento_instagram',
            'estabelecimento_telefone',
        ).first()

        if not estabelecimento:
            logger.error("Estabelecimento não encontrado ou fechado: %s", estab_url)
            return JsonResponse({'status': 'error', 'message': 'Estabelecimento não encontrado ou fechado'}, status=404)

        estabelecimento_id = estabelecimento['id']

        if request.method == 'GET':
            # Tipos de produtos
            tipos = TipoProduto.objects.filter(
                tipo_produto_estabelecimento=estabelecimento_id,
                tipo_produto_ativo=True
            ).values(
                'id',
                'tipo_produto_nome',
                'tipo_aceita_tamanho'
            )

            # Produtos
            produtos = Produto.objects.select_related('produto_tipo').filter(
                produto_estabelecimento=estabelecimento_id,
                produto_ativo=True,
                produto_tipo__tipo_produto_ativo=True
            ).prefetch_related('tamanhos')

            produtos_list = []
            for produto in produtos:
                tamanhos = [
                    {
                        'id': tamanho.id,
                        'nome': tamanho.tamanho_produto_nome,
                        'preco': float(tamanho.tamanho_produto_preco)
                    }
                    for tamanho in produto.tamanhos.filter(
                        tamanho_produto_produto=produto
                    )
                ]
                produtos_list.append({
                    'id': produto.id,
                    'nome': produto.produto_nome,
                    'imagem': produto.produto_imagem.url if produto.produto_imagem else None,
                    'descricao': produto.produto_descricao,
                    'preco': float(produto.produto_preco),
                    'tag': produto.produto_tag,
                    'tipo_id': produto.produto_tipo.id,
                    'tipo_nome': produto.produto_tipo.tipo_produto_nome,
                    'aceita_tamanho': produto.produto_tipo.tipo_aceita_tamanho,
                    'tamanhos': tamanhos
                })

            # Acréscimos
            acrescimos = Acrescimo.objects.filter(
                acrescimo_tipo__tipo_produto_estabelecimento=estabelecimento_id,
                acrescimo_ativo=True
            ).values(
                'id',
                'acrescimo_nome',
                'acrescimo_preco',
                'acrescimo_tipo_id'
            )
            acrescimos_list = [
                {
                    'id': acrescimo['id'],
                    'nome': acrescimo['acrescimo_nome'],
                    'preco': float(acrescimo['acrescimo_preco']),
                    'tipo_id': acrescimo['acrescimo_tipo_id']
                }
                for acrescimo in acrescimos
            ]

            # Promoções
            promocoes = Promocao.objects.filter(
                promocao_estabelecimento=estabelecimento_id,
                promocao_ativo=True
            ).prefetch_related('itens_fixos__produto', 'grupos_itens__itens')

            promocoes_list = []
            for promocao in promocoes:
                # Itens fixos da promoção
                itens_fixos = [
                    {
                        'produto_id': item.produto.id,
                        'nome': item.produto.produto_nome,
                        'quantidade': item.quantidade
                    }
                    for item in promocao.itens_fixos.all()
                ]

                # Grupos de itens selecionáveis
                grupos_itens = [
                    {
                        'id': grupo.id,
                        'nome': grupo.nome,
                        'quantidade_selecionavel': grupo.quantidade_selecionavel,
                        'itens': [
                            {
                                'id': produto.id,
                                'nome': produto.produto_nome,
                                'preco': float(produto.produto_preco)
                            }
                            for produto in grupo.itens.all()
                        ]
                    }
                    for grupo in promocao.grupos_itens.all()
                ]

                promocoes_list.append({
                    'id': promocao.id,
                    'nome': promocao.promocao_nome,
                    'descricao': promocao.promocao_descricao,
                    'preco': float(promocao.promocao_preco) if promocao.promocao_preco else None,
                    'imagem': promocao.promocao_image.url if promocao.promocao_image else None,
                    'ativo': promocao.promocao_ativo,
                    'itens_fixos': itens_fixos,
                    'grupos_itens': grupos_itens
                })

            # Formas de pagamento
            formas_pagamento = FormasDePagamento.objects.filter(
                forma_pagamento_estabelecimento=estabelecimento_id
            ).values(
                'id',
                'forma_pagamento_nome'
            )
            formas_pagamento_list = list(formas_pagamento)

            response_data = {
                'estabelecimento': {
                    'id': estabelecimento['id'],
                    'nome': estabelecimento['estabelecimento_nome'],
                    'logo': estabelecimento['estabelecimento_logo'],
                    'prazo_entrega': estabelecimento['estabelecimento_prazo_entrega'],
                    'chave_pix': estabelecimento['estabelecimento_chave_pix'],
                    'url': estabelecimento['estabelecimento_url'],
                    'instagram': estabelecimento['estabelecimento_instagram'],
                    'whatsapp': estabelecimento['estabelecimento_telefone'],
                },
                'tipos': list(tipos),
                'produtos': produtos_list,
                'acrescimos': acrescimos_list,
                'promocoes': promocoes_list,  # Adicionando as promoções ao response
                'formas_pagamento': formas_pagamento_list
            }

            return JsonResponse(response_data, encoder=DjangoJSONEncoder)

        elif request.method == 'POST':
            logger.info("Corpo da requisição: %s", request.body.decode('utf-8'))
            try:
                data = json.loads(request.body)
                carrinho = data.get('carrinho')
                client_data = data.get('client')
                pagamento_data = data.get('pagamento')
                observacao = data.get('observacao', '')

                # Validações iniciais
                if not carrinho or len(carrinho) == 0:
                    logger.error("Carrinho vazio")
                    return JsonResponse({'status': 'error', 'message': 'Carrinho vazio'}, status=400)
                if not client_data or not pagamento_data:
                    logger.error("Dados de cliente ou pagamento ausentes")
                    return JsonResponse({'status': 'error', 'message': 'Dados de cliente ou pagamento ausentes'}, status=400)
                if not all(key in client_data for key in ['nome', 'telefone', 'endereco']):
                    logger.error("Dados de cliente incompletos")
                    return JsonResponse({'status': 'error', 'message': 'Dados de cliente incompletos'}, status=400)
                if not all(key in client_data['endereco'] for key in ['rua', 'bairro', 'numero']):
                    logger.error("Dados de endereço incompletos")
                    return JsonResponse({'status': 'error', 'message': 'Dados de endereço incompletos'}, status=400)

                # Busca o estabelecimento
                estabelecimento_obj = get_object_or_404(Estabelecimento, id=estabelecimento_id)
                logger.info("Estabelecimento encontrado: %s (ID: %s)", estabelecimento_obj.estabelecimento_nome, estabelecimento_id)

                # Sanitiza telefone
                telefone = ''.join(filter(str.isdigit, client_data['telefone']))
                with transaction.atomic():
                    cliente, created = Cliente.objects.get_or_create(
                        cliente_estabelecimento=estabelecimento_obj,
                        cliente_telefone=telefone,
                        defaults={
                            'cliente_nome': client_data['nome'],
                            'cliente_rua': client_data['endereco']['rua'],
                            'cliente_bairro': client_data['endereco']['bairro'],
                            'cliente_numero': client_data['endereco']['numero'],
                            'cliente_complemento': client_data['endereco']['complemento'] or None,
                        }
                    )
                    logger.info("Cliente %s (ID: %s)", "criado" if created else "encontrado", cliente.id)

                    # Busca a forma de pagamento
                    try:
                        forma_pagamento = FormasDePagamento.objects.get(
                            id=pagamento_data['metodo'],
                            forma_pagamento_estabelecimento=estabelecimento_obj
                        )
                    except FormasDePagamento.DoesNotExist:
                        logger.error("Forma de pagamento inválida: %s", pagamento_data['metodo'])
                        return JsonResponse({'status': 'error', 'message': 'Forma de pagamento inválida'}, status=400)

                    # Cria o pedido
                    pedido = Pedido.objects.create(
                        pedido_estabelecimento=estabelecimento_obj,
                        pedido_cliente=cliente,
                        pedido_observacao=observacao,
                        pedido_forma_pagamento=forma_pagamento,
                        pedido_troco=Decimal(pagamento_data['troco']) if pagamento_data['troco'] else None,
                    )
                    logger.info("Pedido criado: %s", pedido.id)

                    # Processa os itens do carrinho
                    for item in carrinho:
                        logger.info("Processando item: %s", item)
                        try:
                            produto = Produto.objects.get(
                                id=item['produto_id'],
                                produto_estabelecimento=estabelecimento_obj,
                                produto_ativo=True,
                                produto_tipo__tipo_produto_ativo=True
                            )
                            logger.info("Produto encontrado: %s", produto.id)
                        except Produto.DoesNotExist:
                            logger.error("Produto não encontrado ou não pertence ao estabelecimento: %s", item.get('produto_id'))
                            return JsonResponse({'status': 'error', 'message': 'Produto não encontrado ou não pertence ao estabelecimento'}, status=400)

                        tamanho = None
                        if item.get('tamanho_id'):
                            try:
                                tamanho = TamanhoProduto.objects.get(
                                    id=item['tamanho_id'],
                                    tamanho_produto_produto=produto
                                )
                                logger.info("Tamanho encontrado: %s", tamanho.id)
                            except TamanhoProduto.DoesNotExist:
                                logger.error("Tamanho inválido para o produto %s: %s", produto.id, item['tamanho_id'])
                                return JsonResponse(
                                    {'status': 'error', 'message': f'Tamanho inválido para o produto {produto.id}'},
                                    status=400
                                )

                        # Valida preco_unitario
                        expected_price = tamanho.tamanho_produto_preco if tamanho else produto.produto_preco
                        if float(item['preco_unitario']) != float(expected_price):
                            logger.error("Preço unitário inválido para produto %s: enviado %s, esperado %s", item['produto_id'], item['preco_unitario'], expected_price)
                            return JsonResponse({'status': 'error', 'message': 'Preço unitário inválido'}, status=400)

                        try:
                            item_pedido = ItensPedido.objects.create(
                                itens_pedido_estabelecimento=estabelecimento_obj,
                                itens_pedido_pedido=pedido,
                                itens_pedido_produto=produto,
                                itens_pedido_tamanho=tamanho,
                                itens_pedido_quantidade=item['quantidade'],
                                itens_pedido_preco_unitario=Decimal(item['preco_unitario']),
                            )
                            logger.info("Item do pedido criado: %s", item_pedido.id)
                        except Exception as e:
                            logger.error("Erro ao criar item do pedido: %s", str(e))
                            return JsonResponse({'status': 'error', 'message': 'Erro ao criar item do pedido'}, status=400)

                        if 'acrescimos' in item and item['acrescimos']:
                            try:
                                acrescimo_ids = [acrescimo['id'] for acrescimo in item['acrescimos']]
                                acrescimos = Acrescimo.objects.filter(
                                    id__in=acrescimo_ids,
                                    acrescimo_ativo=True,
                                    acrescimo_tipo__tipo_produto_estabelecimento=estabelecimento_obj
                                )
                                if len(acrescimos) != len(acrescimo_ids):
                                    logger.error("Acréscimos não encontrados: %s", acrescimo_ids)
                                    return JsonResponse({'status': 'error', 'message': 'Acréscimo não encontrado'}, status=400)
                                item_pedido.itens_pedido_acrescimos.set(acrescimos)
                                logger.info("Acréscimos associados ao item: %s", [acrescimo.id for acrescimo in acrescimos])
                            except Exception as e:
                                logger.error("Erro ao associar acréscimos: %s", str(e))
                                return JsonResponse({'status': 'error', 'message': 'Erro ao associar acréscimos'}, status=400)

                        try:
                            item_pedido.calcular_preco_final()
                            logger.info("Preço final calculado: %s", item_pedido.itens_pedido_preco_final)
                        except Exception as e:
                            logger.error("Erro ao calcular preço final: %s", str(e))
                            return JsonResponse({'status': 'error', 'message': 'Erro ao calcular preço final'}, status=400)

                    try:
                        pedido.calcular_valor_total()
                        logger.info("Valor total do pedido: %s", pedido.pedido_valor_total)
                    except Exception as e:
                        logger.error("Erro ao calcular valor total do pedido: %s", str(e))
                        return JsonResponse({'status': 'error', 'message': 'Erro ao calcular valor total do pedido'}, status=400)

                # Envia notificação fora da transação
                send_order_notification(pedido)

                return JsonResponse({'status': 'success', 'message': 'Pedido criado com sucesso!', 'pedido_id': pedido.id})

            except json.JSONDecodeError:
                logger.error("Erro ao decodificar JSON: %s", request.body)
                return JsonResponse({'status': 'error', 'message': 'Formato de dados inválido'}, status=400)
            except Exception as e:
                logger.error("Erro inesperado ao processar pedido: %s", str(e))
                return JsonResponse({'status': 'error', 'message': f'Erro ao processar pedido: {str(e)}'}, status=500)

    except Exception as e:
        logger.error("Erro geral na view menu_delivery: %s", str(e))
        return JsonResponse({'status': 'error', 'message': 'Erro interno do servidor'}, status=500)

# View para buscar o cliente pelo telefone
@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def search_client(request, estab_url, phone=None):
    try:
        # Busca o estabelecimento
        estabelecimento = Estabelecimento.objects.filter(
            estabelecimento_url=estab_url,
            estabelecimento_aberto=True
        ).values('id', 'estabelecimento_cidade', 'estabelecimento_estado').first()

        if not estabelecimento:
            logger.error("Estabelecimento não encontrado ou fechado: %s", estab_url)
            return JsonResponse({'status': 'error', 'message': 'Estabelecimento não encontrado ou fechado'}, status=404)

        estabelecimento_id = estabelecimento['id']

        if request.method == 'GET':
            # Busca cliente por telefone
            try:
                cliente = Cliente.objects.get(cliente_telefone=phone, cliente_estabelecimento_id=estabelecimento_id)
                return JsonResponse({
                    'status': True,
                    'cliente': {
                        'cliente_nome': cliente.cliente_nome,
                        'cliente_telefone': cliente.cliente_telefone,
                        'cliente_endereco': {
                            'rua': cliente.cliente_rua,
                            'bairro': cliente.cliente_bairro,
                            'numero': cliente.cliente_numero,
                            'complemento': cliente.cliente_complemento,
                        },
                        'taxa_entrega': float(cliente.cliente_taxa_entrega) if cliente.cliente_taxa_entrega else None
                    }
                })
            except Cliente.DoesNotExist:
                return JsonResponse({'status': False})
            except Exception as e:
                logger.error("Erro ao buscar cliente: %s", str(e))
                return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

        elif request.method == 'POST':
            # Cria ou atualiza cliente e calcula taxa de entrega
            try:
                data = json.loads(request.body)
                telefone = data.get('telefone')
                nome = data.get('nome')
                rua = data.get('rua')
                numero = data.get('numero')
                bairro = data.get('bairro')
                complemento = data.get('complemento', '')

                if not all([telefone, nome, rua, numero, bairro]):
                    logger.error("Dados incompletos: %s", data)
                    return JsonResponse({'status': 'error', 'message': 'Dados incompletos'}, status=400)

                # Cria ou atualiza o cliente
                cliente, created = Cliente.objects.get_or_create(
                    cliente_estabelecimento_id=estabelecimento_id,
                    cliente_telefone=telefone,
                    defaults={
                        'cliente_nome': nome,
                        'cliente_rua': rua,
                        'cliente_bairro': bairro,
                        'cliente_numero': numero,
                        'cliente_complemento': complemento,
                    }
                )

                if not created:
                    # Atualiza os dados do cliente existente
                    cliente.cliente_nome = nome
                    cliente.cliente_rua = rua
                    cliente.cliente_bairro = bairro
                    cliente.cliente_numero = numero
                    cliente.cliente_complemento = complemento

                # Calcula a taxa de entrega se não estiver salva ou se os dados do endereço mudaram
                if not cliente.cliente_taxa_entrega or (
                    cliente.cliente_rua != rua or
                    cliente.cliente_numero != numero or
                    cliente.cliente_bairro != bairro or
                    cliente.cliente_complemento != complemento
                ):
                    client_address = f"{rua}, {numero}, {bairro}, {estabelecimento['estabelecimento_cidade']}, {estabelecimento['estabelecimento_estado']}, Brasil"
                    try:
                        distance_km = calculate_distance(Estabelecimento.objects.get(id=estabelecimento_id), client_address)
                        taxa_entrega = get_delivery_fee(Estabelecimento.objects.get(id=estabelecimento_id), distance_km)
                        cliente.cliente_taxa_entrega = taxa_entrega
                        cliente.save()
                        logger.info(f"Cliente {cliente.id} salvo com taxa de entrega: {taxa_entrega}")
                    except Exception as e:
                        logger.error(f"Erro ao calcular taxa de entrega: {str(e)}")
                        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
                else:
                    taxa_entrega = cliente.cliente_taxa_entrega

                return JsonResponse({
                    'status': 'success',
                    'cliente': {
                        'cliente_nome': cliente.cliente_nome,
                        'cliente_telefone': cliente.cliente_telefone,
                        'cliente_endereco': {
                            'rua': cliente.cliente_rua,
                            'bairro': cliente.cliente_bairro,
                            'numero': cliente.cliente_numero,
                            'complemento': cliente.cliente_complemento,
                        },
                        'taxa_entrega': float(cliente.cliente_taxa_entrega) if cliente.cliente_taxa_entrega else None
                    },
                    'taxa_entrega': float(taxa_entrega)
                })
            except json.JSONDecodeError:
                logger.error("Erro ao decodificar JSON: %s", request.body)
                return JsonResponse({'status': 'error', 'message': 'Formato de dados inválido'}, status=400)
            except Exception as e:
                logger.error("Erro ao criar/atualizar cliente: %s", str(e))
                return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
    except Exception as e:
        logger.error("Erro geral na view search cliente: %s", str(e))
        return JsonResponse({'status': 'error', 'message': 'Erro interno do servidor'}, status=500)

##############################################

## Views da parte administrativa do sistema ##
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def user_data(request):
    user = request.user
    data = {
        'id': user.id,
        'email': user.email,
        'username': user.username,
        'estabelecimento_id': user.profile.estabelecimento.id,
        'estabelecimento_nome': user.profile.estabelecimento.estabelecimento_nome,
        'estabelecimento_aberto': user.profile.estabelecimento.estabelecimento_aberto,
        'estabelecimento_prazo_entrega': user.profile.estabelecimento.estabelecimento_prazo_entrega,
    }
    return Response(data, status=status.HTTP_200_OK)

@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def business(request):
    try:
        logger.info(f"Requisição recebida: {request.data}")
        if not hasattr(request.user, 'profile'):
            logger.error("Usuário sem perfil associado")
            return Response(
                {"error": "Usuário não possui perfil associado"},
                status=status.HTTP_400_BAD_REQUEST
            )

        estabelecimento = request.user.profile.estabelecimento
        if not estabelecimento:
            logger.error("Estabelecimento não encontrado")
            return Response(
                {"error": "Estabelecimento não encontrado"},
                status=status.HTTP_404_NOT_FOUND
            )

        logger.info(f"Estabelecimento atual: id={estabelecimento.id}, aberto={estabelecimento.estabelecimento_aberto}, prazo={estabelecimento.estabelecimento_prazo_entrega}")

        serializer = EstabelecimentoUpdateSerializer(
            estabelecimento,
            data=request.data,
            partial=True
        )
        if serializer.is_valid():
            # Forçar atualização manual para depuração
            validated_data = serializer.validated_data
            logger.info(f"Dados validados: {validated_data}")
            if 'estabelecimento_prazo_entrega' in validated_data:
                estabelecimento.estabelecimento_prazo_entrega = validated_data['estabelecimento_prazo_entrega']
            if 'estabelecimento_aberto' in validated_data:
                estabelecimento.estabelecimento_aberto = validated_data['estabelecimento_aberto']
            estabelecimento.save()
            logger.info(f"Estabelecimento após salvamento: aberto={estabelecimento.estabelecimento_aberto}, prazo={estabelecimento.estabelecimento_prazo_entrega}")
            return Response({
                "mensagem": "Dados do estabelecimento atualizados com sucesso",
                "estabelecimento": {
                    "id": estabelecimento.id,
                    "aberto": estabelecimento.estabelecimento_aberto,
                    "prazo_entrega": estabelecimento.estabelecimento_prazo_entrega,
                }
            }, status=status.HTTP_200_OK)
        else:
            logger.error(f"Erros de validação: {serializer.errors}")
            return Response(
                {"error": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST
            )

    except Exception as e:
        logger.error(f"Erro interno: {str(e)}", exc_info=True)
        return Response(
            {"error": f"Erro interno: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

# View para listar, cadastrar e editar tipos
@api_view(['GET', 'POST', 'PUT'])
@permission_classes([IsAuthenticated])
def types(request, id=None):
    try:
        if request.user.is_superuser:
            tipos = TipoProduto.objects.all()
        else:
            if not hasattr(request.user, 'profile'):
                return Response({"error": "Usuário não possui perfil associado"}, status=status.HTTP_400_BAD_REQUEST)
            estabelecimento = request.user.profile.estabelecimento
            tipos = TipoProduto.objects.filter(tipo_produto_estabelecimento=estabelecimento)

        if request.method == 'GET':
            if id:
                tipo = get_object_or_404(tipos, id=id)
                serializer = TipoProdutoSerializer(tipo)
                return Response({
                    "mensagem": "Detalhes do tipo",
                    "tipo": serializer.data
                })
            else:
                serializer = TipoProdutoSerializer(tipos, many=True)
                return Response({
                    "mensagem": "Lista de tipos",
                    "tipos": serializer.data
                })

        if request.method == 'POST':
            nome = request.POST.get('tipo_nome')
            aceita_tamanho = request.POST.get('tipo_aceita_tamanho') == '1'
            ativo = request.POST.get('tipo_produto_ativo') == '1'

            if not nome:
                return Response({
                    "mensagem": "O campo 'tipo_nome' é obrigatório"
                }, status=status.HTTP_400_BAD_REQUEST)

            try:
                if request.user.is_superuser:
                    # Superusuário precisa especificar o estabelecimento (pode ser ajustado)
                    estabelecimento_id = request.POST.get('estabelecimento_id')
                    if not estabelecimento_id:
                        return Response({
                            "mensagem": "Superusuário deve especificar 'estabelecimento_id'"
                        }, status=status.HTTP_400_BAD_REQUEST)
                    estabelecimento = get_object_or_404(Estabelecimento, id=estabelecimento_id)
                else:
                    estabelecimento = request.user.profile.estabelecimento

                tipo = TipoProduto.objects.create(
                    tipo_produto_estabelecimento=estabelecimento,
                    tipo_produto_nome=nome,
                    tipo_aceita_tamanho=aceita_tamanho,
                    tipo_produto_ativo=ativo
                )
                serializer = TipoProdutoSerializer(tipo)
                return Response({
                    "mensagem": "Tipo criado com sucesso",
                    "tipo": serializer.data
                }, status=status.HTTP_201_CREATED)
            except Exception as e:
                print("Exception:", str(e))
                return Response({
                    "mensagem": "Erro ao criar tipo",
                    "erros": str(e)
                }, status=status.HTTP_400_BAD_REQUEST)

        if request.method == 'PUT':
            if not id:
                return Response({
                    "mensagem": "ID necessário para atualizar um tipo"
                }, status=status.HTTP_400_BAD_REQUEST)

            tipo = get_object_or_404(tipos, id=id)
            nome = request.POST.get('tipo_nome')
            aceita_tamanho = request.POST.get('tipo_aceita_tamanho') == '1'
            ativo = request.POST.get('tipo_produto_ativo') == '1'

            if not nome:
                return Response({
                    "mensagem": "O campo 'tipo_nome' é obrigatório"
                }, status=status.HTTP_400_BAD_REQUEST)

            try:
                tipo.tipo_produto_nome = nome
                tipo.tipo_aceita_tamanho = aceita_tamanho
                tipo.tipo_produto_ativo = ativo
                tipo.save()
                serializer = TipoProdutoSerializer(tipo)
                return Response({
                    "mensagem": "Tipo atualizado com sucesso",
                    "tipo": serializer.data
                }, status=status.HTTP_200_OK)
            except Exception as e:
                print("Exception:", str(e))
                return Response({
                    "mensagem": "Erro ao atualizar tipo",
                    "erros": str(e)
                }, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            "mensagem": "Método não permitido"
        }, status=status.HTTP_405_METHOD_NOT_ALLOWED)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

#View para listar, cadastrar e editar acréscimos
@api_view(['GET', 'POST', 'PUT'])
@permission_classes([IsAuthenticated])
def addons(request, id=None):
    # Define o escopo com base no usuário
    try:
        if request.user.is_superuser:
            acrescimos = Acrescimo.objects.all()
            tipos = TipoProduto.objects.all()
        else:
            if not hasattr(request.user, 'profile'):
                return Response({"error": "Usuário não possui perfil associado"}, status=status.HTTP_400_BAD_REQUEST)
            estabelecimento = request.user.profile.estabelecimento
            acrescimos = Acrescimo.objects.filter(acrescimo_tipo__tipo_produto_estabelecimento=estabelecimento)
            tipos = TipoProduto.objects.filter(tipo_produto_estabelecimento=estabelecimento)

        if request.method == 'GET':
            if id:
                acrescimo = get_object_or_404(acrescimos, id=id)
                serializer = AcrescimoSerializer(acrescimo)
                tipo_serializer = TipoProdutoSerializer(tipos, many=True)
                return Response({
                    "mensagem": "Detalhes do acréscimo",
                    "acrescimo": serializer.data,
                    "tipos": tipo_serializer.data
                })
            else:
                serializer = AcrescimoSerializer(acrescimos, many=True)
                tipo_serializer = TipoProdutoSerializer(tipos, many=True)
                return Response({
                    "mensagem": "Acréscimos e tipos",
                    "acrescimos": serializer.data,
                    "tipos": tipo_serializer.data
                })

        if request.method == 'POST':
            nome = request.POST.get('acrescimo_nome')
            preco = request.POST.get('acrescimo_preco')
            tipo_id = request.POST.get('acrescimo_tipo')
            ativo = request.POST.get('acrescimo_ativo') == '1'

            if not nome or not preco or not tipo_id:
                return Response({
                    "mensagem": "Os campos 'acrescimo_nome', 'acrescimo_preco' e 'acrescimo_tipo' são obrigatórios"
                }, status=status.HTTP_400_BAD_REQUEST)

            try:
                preco = float(preco.replace(',', '.'))
                tipo = get_object_or_404(tipos, id=tipo_id)  # Garante que o tipo pertence ao estabelecimento
                acrescimo = Acrescimo.objects.create(
                    acrescimo_nome=nome,
                    acrescimo_preco=preco,
                    acrescimo_tipo=tipo,
                    acrescimo_ativo=ativo
                )
                serializer = AcrescimoSerializer(acrescimo)
                return Response({
                    "mensagem": "Acréscimo criado com sucesso",
                    "acrescimo": serializer.data
                }, status=status.HTTP_201_CREATED)
            except ValueError:
                return Response({
                    "mensagem": "Preço inválido",
                    "erros": "O campo 'acrescimo_preco' deve ser um número válido"
                }, status=status.HTTP_400_BAD_REQUEST)
            except Exception as e:
                print("Exception:", str(e))
                return Response({
                    "mensagem": "Erro ao criar acréscimo",
                    "erros": str(e)
                }, status=status.HTTP_400_BAD_REQUEST)

        if request.method == 'PUT':
            if not id:
                return Response({
                    "mensagem": "ID necessário para atualizar um acréscimo"
                }, status=status.HTTP_400_BAD_REQUEST)

            acrescimo = get_object_or_404(acrescimos, id=id)
            nome = request.POST.get('acrescimo_nome')
            preco = request.POST.get('acrescimo_preco')
            tipo_id = request.POST.get('acrescimo_tipo')
            ativo = request.POST.get('acrescimo_ativo') == '1'

            if not nome or not preco or not tipo_id:
                return Response({
                    "mensagem": "Os campos 'acrescimo_nome', 'acrescimo_preco' e 'acrescimo_tipo' são obrigatórios"
                }, status=status.HTTP_400_BAD_REQUEST)

            try:
                preco = float(preco.replace(',', '.'))
                tipo = get_object_or_404(tipos, id=tipo_id)  # Garante que o tipo pertence ao estabelecimento
                acrescimo.acrescimo_nome = nome
                acrescimo.acrescimo_preco = preco
                acrescimo.acrescimo_tipo = tipo
                acrescimo.acrescimo_ativo = ativo
                acrescimo.save()
                serializer = AcrescimoSerializer(acrescimo)
                return Response({
                    "mensagem": "Acréscimo atualizado com sucesso",
                    "acrescimo": serializer.data
                }, status=status.HTTP_200_OK)
            except ValueError:
                return Response({
                    "mensagem": "Preço inválido",
                    "erros": "O campo 'acrescimo_preco' deve ser um número válido"
                }, status=status.HTTP_400_BAD_REQUEST)
            except Exception as e:
                print("Exception:", str(e))
                return Response({
                    "mensagem": "Erro ao atualizar acréscimo",
                    "erros": str(e)
                }, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            "mensagem": "Método não permitido"
        }, status=status.HTTP_405_METHOD_NOT_ALLOWED)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# View para listar, cadastrar e editar produtos
@api_view(['GET', 'POST', 'PUT'])
@permission_classes([IsAuthenticated])
def products(request, id=None):
    try:
        if request.user.is_superuser:
            produtos = Produto.objects.all()
            tipos = TipoProduto.objects.all()
            tamanhos = TamanhoProduto.objects.all()
        else:
            if not hasattr(request.user, 'profile'):
                return Response({"error": "Usuário não possui perfil associado"}, status=status.HTTP_400_BAD_REQUEST)
            estabelecimento = request.user.profile.estabelecimento
            produtos = Produto.objects.filter(produto_estabelecimento=estabelecimento)
            tipos = TipoProduto.objects.filter(tipo_produto_estabelecimento=estabelecimento)
            tamanhos = TamanhoProduto.objects.filter(tamanho_produto_produto__produto_estabelecimento=estabelecimento)

        if request.method == 'GET':
            if id:
                produto = get_object_or_404(produtos, id=id)
                tamanhos_produtos = tamanhos.filter(tamanho_produto_produto=produto)
                produto_serializer = ProdutoSerializer(produto)
                tamanho_serializer = TamanhoProdutoSerializer(tamanhos_produtos, many=True)
                return Response({
                    "mensagem": "Detalhes do produto",
                    "produto": produto_serializer.data,
                    "tamanhos": tamanho_serializer.data,
                })
            else:
                produto_serializer = ProdutoSerializer(produtos, many=True)
                tipo_serializer = TipoProdutoSerializer(tipos, many=True)
                return Response({
                    "mensagem": "Listagem de produtos e tipos",
                    "produtos": produto_serializer.data,
                    "tipos": tipo_serializer.data
                })

        if request.method == 'POST':
            form_data = request.POST.copy()
            if 'produto_ativo' not in form_data:
                form_data['produto_ativo'] = '1'

            form = ProdutoForm(form_data, request.FILES)
            formset = TamanhoProdutoFormSet(form_data, prefix='tamanhos')

            tipo_id = form_data.get('produto_tipo')
            tipo_aceita_tamanho = False
            if tipo_id:
                try:
                    tipo_produto = get_object_or_404(tipos, id=tipo_id)
                    tipo_aceita_tamanho = tipo_produto.tipo_aceita_tamanho
                except TipoProduto.DoesNotExist:
                    return Response({
                        "mensagem": "Tipo de produto inválido"
                    }, status=status.HTTP_400_BAD_REQUEST)

            formset_required = tipo_aceita_tamanho and int(form_data.get('tamanhos-TOTAL_FORMS', '0')) > 0

            if form.is_valid() and (not formset_required or formset.is_valid()):
                try:
                    if request.user.is_superuser:
                        estabelecimento_id = form_data.get('estabelecimento_id')
                        if not estabelecimento_id:
                            return Response({
                                "mensagem": "Superusuário deve especificar 'estabelecimento_id'"
                            }, status=status.HTTP_400_BAD_REQUEST)
                        estabelecimento = get_object_or_404(Estabelecimento, id=estabelecimento_id)
                    else:
                        estabelecimento = request.user.profile.estabelecimento

                    produto = form.save(commit=False)
                    produto.produto_estabelecimento = estabelecimento
                    produto.save()
                    if formset_required:
                        formset.instance = produto
                        formset.save()
                    produto_serializer = ProdutoSerializer(produto)
                    tamanhos_produtos = tamanhos.filter(tamanho_produto_produto=produto)
                    tamanho_serializer = TamanhoProdutoSerializer(tamanhos_produtos, many=True)
                    return Response({
                        "mensagem": "Produto criado com sucesso",
                        "produto": produto_serializer.data,
                        "tamanhos": tamanho_serializer.data
                    }, status=status.HTTP_201_CREATED)
                except Exception as e:
                    print("Exception:", str(e))
                    return Response({
                        "mensagem": "Erro ao criar produto",
                        "erros": str(e)
                    }, status=status.HTTP_400_BAD_REQUEST)
            else:
                erros = {}
                if not form.is_valid():
                    erros['produto'] = form.errors
                if formset_required and not formset.is_valid():
                    erros['tamanhos'] = formset.errors
                return Response({
                    "mensagem": "Erro de validação",
                    "erros": erros
                }, status=status.HTTP_400_BAD_REQUEST)

        if request.method == 'PUT':
            produto = get_object_or_404(produtos, id=id)
            if 'produto_ativo' in request.data and len(request.data) == 1:
                try:
                    ativo_value = request.data['produto_ativo']
                    if isinstance(ativo_value, str):
                        ativo_value = int(ativo_value)
                    produto.produto_ativo = bool(ativo_value)
                    produto.save()
                    serializer = ProdutoSerializer(produto)
                    return Response({
                        "mensagem": "Status do produto atualizado",
                        "produto": serializer.data
                    }, status=status.HTTP_200_OK)
                except (ValueError, TypeError) as e:
                    print("Exception:", str(e))
                    return Response({
                        "mensagem": "Erro ao atualizar status do produto",
                        "erros": f"Valor inválido para produto_ativo: {request.data['produto_ativo']}"
                    }, status=status.HTTP_400_BAD_REQUEST)
            else:
                form_data = request.POST.copy()
                # Converter produto_ativo de "0"/"1" para valores booleanos
                if 'produto_ativo' in form_data:
                    form_data['produto_ativo'] = 'True' if form_data['produto_ativo'] == '1' else 'False'
                else:
                    form_data['produto_ativo'] = 'False'  # Caso o campo esteja ausente, define como inativo

                form = ProdutoForm(form_data, request.FILES, instance=produto)
                formset = TamanhoProdutoFormSet(form_data, instance=produto, prefix='tamanhos')

                tipo_id = form_data.get('produto_tipo')
                tipo_aceita_tamanho = False
                if tipo_id:
                    try:
                        tipo_produto = get_object_or_404(tipos, id=tipo_id)
                        tipo_aceita_tamanho = tipo_produto.tipo_aceita_tamanho
                    except TipoProduto.DoesNotExist:
                        return Response({
                            "mensagem": "Tipo de produto inválido"
                        }, status=status.HTTP_400_BAD_REQUEST)

                formset_required = tipo_aceita_tamanho and int(form_data.get('tamanhos-TOTAL_FORMS', '0')) > 0

                if form.is_valid() and (not formset_required or formset.is_valid()):
                    try:
                        produto = form.save()
                        if formset_required:
                            formset.instance = produto
                            formset.save()
                        else:
                            tamanhos.filter(tamanho_produto_produto=produto).delete()
                        produto_serializer = ProdutoSerializer(produto)
                        tamanhos_produtos = tamanhos.filter(tamanho_produto_produto=produto)
                        tamanho_serializer = TamanhoProdutoSerializer(tamanhos_produtos, many=True)
                        return Response({
                            "mensagem": "Produto atualizado com sucesso",
                            "produto": produto_serializer.data,
                            "tamanhos": tamanho_serializer.data
                        }, status=status.HTTP_200_OK)
                    except Exception as e:
                        print("Exception:", str(e))
                        return Response({
                            "mensagem": "Erro ao atualizar produto",
                            "erros": str(e)
                        }, status=status.HTTP_400_BAD_REQUEST)
                else:
                    erros = {}
                    if not form.is_valid():
                        erros['produto'] = form.errors
                    if formset_required and not formset.is_valid():
                        erros['tamanhos'] = formset.errors
                    return Response({
                        "mensagem": "Erro de validação",
                        "erros": erros
                    }, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            "mensagem": "Método não permitido"
        }, status=status.HTTP_405_METHOD_NOT_ALLOWED)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
# View para listar, cadastrar e editar promoções    
import json
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404
from .models import Promocao, Estabelecimento
from .serializers import PromocaoSerializer

@api_view(['GET', 'POST', 'PUT'])
@permission_classes([IsAuthenticated])
def promo(request, id=None):
    print(f"Recebida requisição: {request.method} para URL: {request.path} com ID: {id}")  # Log para depuração
    try:
        # Filtragem de promoções por estabelecimento
        if request.user.is_superuser:
            promocoes = Promocao.objects.all()
        else:
            if not hasattr(request.user, 'profile'):
                return Response({"error": "Usuário não possui perfil associado"}, status=status.HTTP_400_BAD_REQUEST)
            estabelecimento = request.user.profile.estabelecimento
            promocoes = Promocao.objects.filter(promocao_estabelecimento=estabelecimento)

        # GET: Listar ou detalhar promoção
        if request.method == 'GET':
            print("Processando GET")
            if id:
                promocao = get_object_or_404(promocoes, id=id)
                serializer = PromocaoSerializer(promocao)
                return Response({
                    "mensagem": "Detalhes da promoção",
                    "promocao": serializer.data
                })
            else:
                serializer = PromocaoSerializer(promocoes, many=True)
                return Response({
                    "mensagem": "Listagem de promoções",
                    "promocoes": serializer.data
                })

        # POST: Criar nova promoção
        if request.method == 'POST':
            print("Processando POST")
            form_data = request.data.copy()
            print("Form data original:", dict(form_data))  # Log para depuração

            # Criar um dicionário para os dados processados
            processed_data = {}

            # Processar campos simples
            for field in ['promocao_nome', 'promocao_descricao', 'promocao_preco', 'promocao_ativo']:
                if field in form_data:
                    value = form_data[field]
                    if isinstance(value, list) and len(value) > 0:
                        processed_data[field] = value[0]
                    else:
                        processed_data[field] = value
                elif field == 'promocao_ativo':
                    processed_data['promocao_ativo'] = 'true'

            # Processar itens_fixos
            if 'itens_fixos' in form_data:
                itens_fixos_value = form_data['itens_fixos']
                if isinstance(itens_fixos_value, list) and len(itens_fixos_value) > 0:
                    itens_fixos_value = itens_fixos_value[0]
                if isinstance(itens_fixos_value, str):
                    try:
                        parsed_itens_fixos = json.loads(itens_fixos_value)
                        processed_data['itens_fixos'] = parsed_itens_fixos
                    except json.JSONDecodeError as e:
                        return Response({
                            "mensagem": "Erro de validação",
                            "erros": {"itens_fixos": f"Formato JSON inválido: {str(e)}"}
                        }, status=status.HTTP_400_BAD_REQUEST)
                else:
                    processed_data['itens_fixos'] = itens_fixos_value

            # Processar grupos_itens
            if 'grupos_itens' in form_data:
                grupos_itens_value = form_data['grupos_itens']
                if isinstance(grupos_itens_value, list) and len(grupos_itens_value) > 0:
                    grupos_itens_value = grupos_itens_value[0]
                if isinstance(grupos_itens_value, str):
                    try:
                        parsed_grupos_itens = json.loads(grupos_itens_value)
                        processed_data['grupos_itens'] = parsed_grupos_itens
                    except json.JSONDecodeError as e:
                        return Response({
                            "mensagem": "Erro de validação",
                            "erros": {"grupos_itens": f"Formato JSON inválido: {str(e)}"}
                        }, status=status.HTTP_400_BAD_REQUEST)
                else:
                    processed_data['grupos_itens'] = grupos_itens_value

            # Processar promocao_image
            if 'promocao_image' in form_data:
                processed_data['promocao_image'] = form_data['promocao_image']

            # Validação do estabelecimento
            if request.user.is_superuser:
                estabelecimento_id = form_data.get('promocao_estabelecimento')
                if not estabelecimento_id:
                    return Response({
                        "mensagem": "Superusuário deve especificar 'promocao_estabelecimento'"
                    }, status=status.HTTP_400_BAD_REQUEST)
                estabelecimento = get_object_or_404(Estabelecimento, id=estabelecimento_id)
                processed_data['promocao_estabelecimento'] = estabelecimento.id
            else:
                estabelecimento = request.user.profile.estabelecimento
                processed_data['promocao_estabelecimento'] = estabelecimento.id

            print("Processed data:", processed_data)  # Log para depuração

            serializer = PromocaoSerializer(data=processed_data)
            if serializer.is_valid():
                promocao = serializer.save()
                return Response({
                    "mensagem": "Promoção criada com sucesso",
                    "promocao": PromocaoSerializer(promocao).data
                }, status=status.HTTP_201_CREATED)
            print("Erros de validação:", serializer.errors)  # Log para depuração
            return Response({
                "mensagem": "Erro de validação",
                "erros": serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)

        # PUT: Editar promoção existente
        if request.method == 'PUT':
            print("Processando PUT para ID:", id)  # Log para depuração
            promocao = get_object_or_404(promocoes, id=id)
            form_data = request.data.copy()
            print("Form data original:", dict(form_data))  # Log para depuração

            # Desaninhar campos simples
            for field in ['promocao_nome', 'promocao_descricao', 'promocao_preco', 'promocao_ativo']:
                if field in form_data and isinstance(form_data[field], list) and len(form_data[field]) > 0:
                    form_data[field] = form_data[field][0]

            # Processar promocao_ativo
            if 'promocao_ativo' in form_data:
                form_data['promocao_ativo'] = form_data['promocao_ativo'].lower() == 'true'
            else:
                form_data['promocao_ativo'] = False

            # Deserializar itens_fixos
            if 'itens_fixos' in form_data:
                itens_fixos_value = form_data['itens_fixos']
                if isinstance(itens_fixos_value, list) and len(itens_fixos_value) > 0:
                    itens_fixos_value = itens_fixos_value[0]
                if isinstance(itens_fixos_value, str):
                    try:
                        form_data['itens_fixos'] = json.loads(itens_fixos_value)
                    except json.JSONDecodeError as e:
                        return Response({
                            "mensagem": "Erro de validação",
                            "erros": {"itens_fixos": f"Formato JSON inválido: {str(e)}"}
                        }, status=status.HTTP_400_BAD_REQUEST)

            # Deserializar grupos_itens
            if 'grupos_itens' in form_data:
                grupos_itens_value = form_data['grupos_itens']
                if isinstance(grupos_itens_value, list) and len(grupos_itens_value) > 0:
                    grupos_itens_value = grupos_itens_value[0]
                if isinstance(grupos_itens_value, str):
                    try:
                        form_data['grupos_itens'] = json.loads(grupos_itens_value)
                    except json.JSONDecodeError as e:
                        return Response({
                            "mensagem": "Erro de validação",
                            "erros": {"grupos_itens": f"Formato JSON inválido: {str(e)}"}
                        }, status=status.HTTP_400_BAD_REQUEST)

            # Validação do estabelecimento
            if request.user.is_superuser:
                estabelecimento_id = form_data.get('promocao_estabelecimento')
                if not estabelecimento_id:
                    return Response({
                        "mensagem": "Superusuário deve especificar 'promocao_estabelecimento'"
                    }, status=status.HTTP_400_BAD_REQUEST)
                estabelecimento = get_object_or_404(Estabelecimento, id=estabelecimento_id)
                form_data['promocao_estabelecimento'] = estabelecimento.id
            else:
                estabelecimento = request.user.profile.estabelecimento
                form_data['promocao_estabelecimento'] = estabelecimento.id

            print("Form data após parsing:", dict(form_data))  # Log para depuração

            serializer = PromocaoSerializer(instance=promocao, data=form_data, partial=True)
            if serializer.is_valid():
                promocao = serializer.save()
                return Response({
                    "mensagem": "Promoção atualizada com sucesso",
                    "promocao": PromocaoSerializer(promocao).data
                }, status=status.HTTP_200_OK)
            print("Erros de validação:", serializer.errors)  # Log para depuração
            return Response({
                "mensagem": "Erro de validação",
                "erros": serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            "mensagem": "Método não permitido"
        }, status=status.HTTP_405_METHOD_NOT_ALLOWED)

    except Exception as e:
        print("Erro geral:", str(e))  # Log para depuração
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# View para listar e atualizar pedidos
@api_view(['GET', 'PUT'])
@permission_classes([IsAuthenticated])
def orders(request, id=None):
    # Define o escopo com base no usuário
    try:
        if request.user.is_superuser:
            pedidos = Pedido.objects.all()
        else:
            if not hasattr(request.user, 'profile'):
                return Response({"error": "Usuário não possui perfil associado"}, status=status.HTTP_400_BAD_REQUEST)
            estabelecimento = request.user.profile.estabelecimento
            pedidos = Pedido.objects.filter(pedido_estabelecimento=estabelecimento)

        if request.method == 'GET':
            if id:
                pedido = get_object_or_404(pedidos, id=id)
                pedido = pedidos.filter(id=id).prefetch_related(
                    Prefetch('itens', queryset=ItensPedido.objects.select_related(
                        'itens_pedido_produto', 'itens_pedido_tamanho'
                    ).prefetch_related('itens_pedido_acrescimos'))
                ).first()
                serializer = PedidoSerializer(pedido)
                return Response({
                    "mensagem": "Detalhes do pedido",
                    "pedido": serializer.data
                })
            else:
                status_param = request.GET.get('status', 'pending')
                pedidos = pedidos.filter(pedido_status=status_param).prefetch_related(
                    Prefetch('itens', queryset=ItensPedido.objects.select_related(
                        'itens_pedido_produto', 'itens_pedido_tamanho'
                    ).prefetch_related('itens_pedido_acrescimos'))
                )
                serializer = PedidoSerializer(pedidos, many=True)
                return Response({
                    "mensagem": "Lista de pedidos",
                    "pedidos": serializer.data
                })

        if request.method == 'PUT':
            if not id:
                return Response({
                    "mensagem": "ID necessário para atualizar um pedido"
                }, status=status.HTTP_400_BAD_REQUEST)

            pedido = get_object_or_404(pedidos, id=id)
            novo_status = request.data.get('status')
            if novo_status not in ['pending', 'preparing', 'ready', 'delivery', 'completed', 'cancelled']:
                return Response({
                    "mensagem": "Status inválido"
                }, status=status.HTTP_400_BAD_REQUEST)

            # Verifica se é uma transição de pending para preparing
            send_whatsapp = (pedido.pedido_status == 'pending' and novo_status == 'preparing')

            try:
                pedido.pedido_status = novo_status
                pedido.save()

                # Envia mensagem no WhatsApp se for transição de pending para preparing
                if send_whatsapp:
                    try:
                        client_phone = pedido.pedido_cliente.cliente_telefone
                        client_name = pedido.pedido_cliente.cliente_nome
                        order_number = str(pedido.id).zfill(6)  # Formata como 000123

                        # Configurações da Evolution API
                        evolution_api_url = config('EVOLUTION_API_URL')
                        print(evolution_api_url)
                        evolution_instance = config('EVOLUTION_API_INSTANCE')
                        evolution_api_key = config('EVOLUTION_API_KEY')

                        # Monta a URL e o payload
                        url = f"{evolution_api_url}/message/sendText/{evolution_instance}"
                        headers = {
                            'Content-Type': 'application/json',
                            'apiKey': evolution_api_key
                        }
                        payload = {
                            "number": f'55{client_phone}',
                            "text": f"Olá, {client_name}! Seu pedido #{order_number} começou a ser preparado. Te avisaremos quando estiver pronto! 😊"
                        }

                        # Envia a mensagem
                        response = requests.post(url, json=payload, headers=headers)
                        if response.status_code != 200:
                            print(f"Erro ao enviar mensagem WhatsApp: {response.text}")
                            return Response({
                                "mensagem": "Status do pedido atualizado, mas falha ao enviar mensagem WhatsApp",
                                "pedido": PedidoSerializer(pedido).data,
                                "aviso": "Não foi possível notificar o cliente via WhatsApp"
                            }, status=status.HTTP_200_OK)

                    except Exception as e:
                        print(f"Exceção ao enviar WhatsApp: {str(e)}")
                        return Response({
                            "mensagem": "Status do pedido atualizado, mas falha ao enviar mensagem WhatsApp",
                            "pedido": PedidoSerializer(pedido).data,
                            "aviso": f"Erro ao notificar cliente: {str(e)}"
                        }, status=status.HTTP_200_OK)

                serializer = PedidoSerializer(pedido)
                return Response({
                    "mensagem": "Status do pedido atualizado",
                    "pedido": serializer.data
                }, status=status.HTTP_200_OK)

            except Exception as e:
                print("Exception:", str(e))
                return Response({
                    "mensagem": "Erro ao atualizar pedido",
                    "erros": str(e)
                }, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            "mensagem": "Método não permitido"
        }, status=status.HTTP_405_METHOD_NOT_ALLOWED)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
# View para alternar o status ativo de produtos, tipos e acréscimos
class ToggleActiveView(APIView):
    # Mapeamento de nomes de modelo para classes e serializers
    MODEL_MAP = {
        'produto': {
            'model': Produto,
            'serializer': ProdutoSerializer,
            'active_field': 'produto_ativo'
        },
        'tipo': {
            'model': TipoProduto,
            'serializer': TipoProdutoSerializer,
            'active_field': 'tipo_produto_ativo'
        },
        'acrescimo': {
            'model': Acrescimo,
            'serializer': AcrescimoSerializer,
            'active_field': 'acrescimo_ativo'
        }
    }

    def post(self, request, model_name, id):
        try:
            # Verifica se o modelo é válido
            model_info = self.MODEL_MAP.get(model_name.lower())
            if not model_info:
                return Response(
                    {'error': f'Modelo "{model_name}" inválido. Modelos válidos: {", ".join(self.MODEL_MAP.keys())}'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            model_class = model_info['model']
            serializer_class = model_info['serializer']
            active_field = model_info['active_field']

            # Filtra objetos com base no usuário
            if request.user.is_superuser:
                queryset = model_class.objects.all()
            else:
                if not hasattr(request.user, 'profile'):
                    return Response(
                        {"error": "Usuário não possui perfil associado"},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                estabelecimento = request.user.profile.estabelecimento
                if model_name == 'produto':
                    queryset = model_class.objects.filter(produto_estabelecimento=estabelecimento)
                elif model_name == 'tipo':
                    queryset = model_class.objects.filter(tipo_produto_estabelecimento=estabelecimento)
                elif model_name == 'acrescimo':
                    queryset = model_class.objects.filter(acrescimo_tipo__tipo_produto_estabelecimento=estabelecimento)

            # Busca o objeto
            obj = get_object_or_404(queryset, id=id)

            # Alterna o campo ativo
            current_status = getattr(obj, active_field)
            setattr(obj, active_field, not current_status)
            obj.save()

            # Serializa o objeto atualizado
            serializer = serializer_class(obj)
            return Response(
                {
                    "mensagem": f"Status de {model_name} atualizado com sucesso",
                    "data": serializer.data
                },
                status=status.HTTP_200_OK
            )

        except Exception as e:
            return Response(
                {"error": f"Erro ao atualizar status: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

# View para imprimir os pedidos
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def print_order(request, id):
    try:
        if request.user.is_superuser:
            logger.info(f"Superusuário acessando pedido ID {id}")
            pedido = get_object_or_404(Pedido, id=id)
        else:
            if not hasattr(request.user, 'profile'):
                logger.error("Usuário sem perfil associado")
                return Response({"error": "Usuário não possui perfil associado"}, status=400)
            estabelecimento = request.user.profile.estabelecimento
            logger.info(f"Buscando pedido ID {id} para estabelecimento {estabelecimento.id}")
            pedido = get_object_or_404(Pedido, id=id, pedido_estabelecimento=estabelecimento)

        logger.info(f"Pedido encontrado: {pedido.id}")
        context = {
            'pedido': pedido,
            'itens': pedido.itens.all(),
            'logo_url': request.build_absolute_uri(pedido.pedido_estabelecimento.estabelecimento_logo.url) if pedido.pedido_estabelecimento.estabelecimento_logo else None,
        }
        logger.info("Renderizando template order_print.html")
        html_string = render_to_string('delivery/order_print.html', context) 
        logger.info("Gerando PDF com WeasyPrint")
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="pedido_{pedido.id}.pdf"'
        HTML(string=html_string).write_pdf(response)
        logger.info(f"PDF gerado para pedido {pedido.id}")
        return response
    except Exception as e:
        logger.error(f"Erro ao gerar PDF para pedido ID {id}: {str(e)}", exc_info=True)
        return Response({"error": str(e)}, status=500)
##############################################