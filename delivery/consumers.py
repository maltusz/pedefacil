import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async

class OrderConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        # Obtém o estabelecimento_id da URL (e.g., ws://localhost:8000/ws/orders/1/)
        self.estabelecimento_id = self.scope['url_route']['kwargs']['estabelecimento_id']
        self.group_name = f'orders_{self.estabelecimento_id}'

        # Obtém o token da query string (e.g., ?token=<jwt>)
        query_string = self.scope['query_string'].decode()
        token = None
        for param in query_string.split('&'):
            if param.startswith('token='):
                token = param[len('token='):]
                break

        # Valida o token e o estabelecimento
        if await self.validate_connection(token):
            # Adiciona ao grupo
            await self.channel_layer.group_add(self.group_name, self.channel_name)
            await self.accept()
        else:
            # Rejeita a conexão
            await self.close()

    @database_sync_to_async
    def validate_connection(self, token):
        # Importações movidas para dentro da função
        from django.contrib.auth.models import User
        from rest_framework_simplejwt.tokens import AccessToken
        from .models import Estabelecimento, UserProfile

        try:
            if not token:
                return False

            # Valida o token JWT
            access_token = AccessToken(token)
            user_id = access_token['user_id']
            user = User.objects.get(id=user_id)

            # Verifica se o usuário está associado ao estabelecimento
            user_profile = UserProfile.objects.get(user=user)
            estabelecimento = Estabelecimento.objects.get(id=self.estabelecimento_id)
            return user_profile.estabelecimento == estabelecimento
        except (AccessToken.InvalidToken, User.DoesNotExist, UserProfile.DoesNotExist, Estabelecimento.DoesNotExist):
            return False

    async def disconnect(self, close_code):
        # Remove do grupo
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data):
        # Não esperamos mensagens do cliente, mas pode ser expandido
        pass

    async def new_order(self, event):
        # Envia a notificação para o cliente
        order = event['order']
        await self.send(text_data=json.dumps({
            'type': 'new_order',
            'order': order
        }))