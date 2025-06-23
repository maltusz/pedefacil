from django.core.management.base import BaseCommand
from delivery.models import Pedido

class Command(BaseCommand):
    help = 'Recalcula pedido_valor_total para todos os pedidos'

    def handle(self, *args, **kwargs):
        pedidos = Pedido.objects.all()
        for pedido in pedidos:
            pedido.calcular_valor_total()
            self.stdout.write(self.style.SUCCESS(f'Atualizado pedido {pedido.id}'))