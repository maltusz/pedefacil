from rest_framework import serializers
from .models import Produto, TipoProduto, TamanhoProduto, Acrescimo, Cliente, Pedido, FormasDePagamento, ItensPedido, Estabelecimento, ItensPromocao, GrupoItensPromocao, Promocao

class EstabelecimentoUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Estabelecimento
        fields = ['estabelecimento_prazo_entrega', 'estabelecimento_aberto']
    
    def validate_estabelecimento_prazo_entrega(self, value):
        if value is None:
            raise serializers.ValidationError("Este campo é obrigatório.")
        if value < 0:
            raise serializers.ValidationError("Prazo de entrega não pode ser negativo.")
        return value

class ClientAddressSerializer(serializers.Serializer):
    rua = serializers.CharField(max_length=200)
    numero = serializers.CharField(max_length=10)
    bairro = serializers.CharField(max_length=100, required=False, allow_blank=True)
    complemento = serializers.CharField(max_length=100, required=False, allow_blank=True)
    cidade = serializers.CharField(max_length=100, required=False, allow_blank=True)
    estado = serializers.CharField(max_length=2, required=False, allow_blank=True)

class DeliveryFeeRequestSerializer(serializers.Serializer):
    estabelecimento_id = serializers.PrimaryKeyRelatedField(queryset=Estabelecimento.objects.all())
    client_address = ClientAddressSerializer()

class DeliveryFeeResponseSerializer(serializers.Serializer):
    distance_km = serializers.FloatField()
    delivery_fee = serializers.DecimalField(max_digits=10, decimal_places=2)

class ProdutoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Produto
        fields = '__all__'

class TipoProdutoSerializer(serializers.ModelSerializer):
    class Meta:
        model = TipoProduto
        fields = '__all__'

class TamanhoProdutoSerializer(serializers.ModelSerializer):
    class Meta:
        model = TamanhoProduto
        fields = '__all__'

class AcrescimoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Acrescimo
        fields = '__all__'

class ClienteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Cliente
        fields = '__all__'

class FormasDePagamentoSerializer(serializers.ModelSerializer):
    class Meta:
        model = FormasDePagamento
        fields = '__all__'

class ItensPedidoSerializer(serializers.ModelSerializer):
    itens_pedido_produto = ProdutoSerializer()
    itens_pedido_tamanho = TamanhoProdutoSerializer(allow_null=True)
    itens_pedido_acrescimos = AcrescimoSerializer(many=True)

    class Meta:
        model = ItensPedido
        fields = [
            'id',
            'itens_pedido_produto',
            'itens_pedido_tamanho',
            'itens_pedido_quantidade',
            'itens_pedido_preco_unitario',
            'itens_pedido_acrescimos',
            'itens_pedido_preco_final'
        ]

class PedidoSerializer(serializers.ModelSerializer):
    pedido_cliente = ClienteSerializer()
    pedido_forma_pagamento = FormasDePagamentoSerializer()
    itens = ItensPedidoSerializer(many=True)

    class Meta:
        model = Pedido
        fields = [
            'id',
            'pedido_data',
            'pedido_status',
            'pedido_observacao',
            'pedido_valor_total',
            'pedido_forma_pagamento',
            'pedido_troco',
            'pedido_cliente',
            'itens',
            'pedido_tipo_entrega',
        ]

class ItensPromocaoSerializer(serializers.ModelSerializer):
    produto = serializers.PrimaryKeyRelatedField(queryset=Produto.objects.all())

    class Meta:
        model = ItensPromocao
        fields = ['id', 'produto', 'quantidade']

    def validate_produto(self, value):
        if not Produto.objects.filter(id=value.id).exists():
            raise serializers.ValidationError(f"Produto com ID {value.id} não existe")
        return value

class GrupoItensPromocaoSerializer(serializers.ModelSerializer):
    itens = serializers.PrimaryKeyRelatedField(queryset=Produto.objects.all(), many=True)

    class Meta:
        model = GrupoItensPromocao
        fields = ['id', 'nome', 'quantidade_selecionavel', 'itens']

    def validate_itens(self, value):
        if not value:
            raise serializers.ValidationError("Pelo menos um item deve ser selecionado")
        for item in value:
            if not Produto.objects.filter(id=item.id).exists():
                raise serializers.ValidationError(f"Produto com ID {item.id} não existe")
        return value

class PromocaoSerializer(serializers.ModelSerializer):
    promocao_image = serializers.ImageField(required=False, allow_null=True)
    itens_fixos = ItensPromocaoSerializer(many=True, required=True)  # Tornar obrigatório
    grupos_itens = GrupoItensPromocaoSerializer(many=True, required=True)  # Tornar obrigatório
    promocao_estabelecimento = serializers.PrimaryKeyRelatedField(queryset=Estabelecimento.objects.all())

    class Meta:
        model = Promocao
        fields = [
            'id', 'promocao_estabelecimento', 'promocao_image', 'promocao_nome', 'promocao_descricao',
            'promocao_preco', 'promocao_ativo', 'itens_fixos', 'grupos_itens'
        ]

    def validate(self, data):
        print("Dados recebidos no serializer:", data)  # Log para depuração
        return data

    def create(self, validated_data):
        print("Validated data:", validated_data)  # Log para depuração
        itens_fixos_data = validated_data.pop('itens_fixos', [])
        print("Itens fixos:", itens_fixos_data)  # Log para depuração
        grupos_itens_data = validated_data.pop('grupos_itens', [])
        print("Grupos itens:", grupos_itens_data)  # Log para depuração
        promocao = Promocao.objects.create(**validated_data)

        for item_data in itens_fixos_data:
            ItensPromocao.objects.create(promocao=promocao, **item_data)

        for grupo_data in grupos_itens_data:
            itens = grupo_data.pop('itens', [])
            grupo = GrupoItensPromocao.objects.create(promocao=promocao, **grupo_data)
            grupo.itens.set(itens)

        return promocao

    def update(self, instance, validated_data):
        print("Validated data (update):", validated_data)  # Log para depuração
        itens_fixos_data = validated_data.pop('itens_fixos', None)
        print("Itens fixos (update):", itens_fixos_data)  # Log para depuração
        grupos_itens_data = validated_data.pop('grupos_itens', None)
        print("Grupos itens (update):", grupos_itens_data)  # Log para depuração

        # Atualiza os campos da promoção
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        # Atualiza itens fixos
        if itens_fixos_data is not None:
            instance.itens_fixos.all().delete()
            for item_data in itens_fixos_data:
                ItensPromocao.objects.create(promocao=instance, **item_data)

        # Atualiza grupos de itens
        if grupos_itens_data is not None:
            instance.grupos_itens.all().delete()
            for grupo_data in grupos_itens_data:
                itens = grupo_data.pop('itens', [])
                grupo = GrupoItensPromocao.objects.create(promocao=instance, **grupo_data)
                grupo.itens.set(itens)

        return instance