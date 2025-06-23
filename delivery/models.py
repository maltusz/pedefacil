from decimal import Decimal
from django.db import models
from django.contrib.auth.models import User
from django import forms
from django.forms import inlineformset_factory

from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

class Estabelecimento(models.Model):
    estabelecimento_nome = models.CharField(max_length=255)
    estabelecimento_url = models.SlugField(max_length=255, unique=True)  
    estabelecimento_cnpj = models.CharField(max_length=14, unique=True)  
    estabelecimento_chave_pix = models.CharField(max_length=255, blank=True, null=True, unique=True)  
    estabelecimento_logo = models.ImageField(upload_to='delivery/imgs')
    estabelecimento_proprietario = models.CharField(max_length=255)
    estabelecimento_telefone = models.CharField(max_length=20, unique=True)
    estabelecimento_instagram = models.CharField(max_length=50)
    estabelecimento_email = models.EmailField(unique=True)  
    estabelecimento_endereco = models.CharField(max_length=255)
    estabelecimento_bairro = models.CharField(max_length=255)
    estabelecimento_numero = models.CharField(max_length=10)
    estabelecimento_complemento = models.CharField(max_length=100, blank=True, null=True)
    estabelecimento_cidade = models.CharField(max_length=100)
    estabelecimento_estado = models.CharField(max_length=2)
    estabelecimento_latitude = models.FloatField()
    estabelecimento_longitude = models.FloatField()
    estabelecimento_prazo_entrega = models.IntegerField(default=0)
    estabelecimento_aberto = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Estabelecimento"
        verbose_name_plural = "Estabelecimentos"

    def __str__(self):
        return self.estabelecimento_nome

class DeliveryRange(models.Model):
    estabelecimento = models.ForeignKey(
        Estabelecimento,
        on_delete=models.CASCADE,
        related_name="delivery_ranges",
        verbose_name="Estabelecimento"
    )
    min_distance = models.FloatField(verbose_name="Distância mínima (km)")
    max_distance = models.FloatField(verbose_name="Distância máxima (km)")
    delivery_fee = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Taxa de entrega (R$)")
    
    class Meta:
        verbose_name = "Faixa de entrega"
        verbose_name_plural = "Faixas de entrega"
        ordering = ['min_distance']
        constraints = [
                models.UniqueConstraint(
                    fields=['estabelecimento', 'min_distance', 'max_distance'],
                    name='unique_delivery_range_per_estabelecimento'
                )
            ]

    def __str__(self):
            return f"{self.estabelecimento.estabelecimento_nome}: {self.min_distance}km - {self.max_distance}km: R${self.delivery_fee}"

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    estabelecimento = models.ForeignKey(Estabelecimento, on_delete=models.CASCADE, related_name='users')

    class Meta:
        verbose_name = "Perfil de Usuário"
        verbose_name_plural = "Perfis de Usuários"

    def __str__(self):
        return f"{self.user.username} ({self.estabelecimento.estabelecimento_nome})"
    
class TipoProduto(models.Model):
    tipo_produto_estabelecimento = models.ForeignKey(Estabelecimento, on_delete=models.CASCADE, related_name='tipo_produto')
    tipo_produto_nome = models.CharField(max_length=50)
    tipo_aceita_tamanho = models.BooleanField(default=False)
    tipo_produto_ativo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Tipo de Produto"
        verbose_name_plural = "Tipos de Produto"
        indexes = [
            models.Index(fields=['tipo_produto_estabelecimento']),
        ]

    def __str__(self):
        return self.tipo_produto_nome

class Produto(models.Model):
    produto_estabelecimento = models.ForeignKey(Estabelecimento, on_delete=models.CASCADE, related_name='produto')
    produto_nome = models.CharField(max_length=255)
    produto_descricao = models.TextField()
    produto_preco = models.DecimalField(max_digits=10, decimal_places=2)
    produto_imagem = models.ImageField(upload_to='delivery/imgs')
    produto_tipo = models.ForeignKey(TipoProduto, on_delete=models.CASCADE, related_name='tipo_produto')
    produto_ativo = models.BooleanField(default=True)
    produto_tag = models.CharField(max_length=255, blank=True, null=True)
    
    class Meta:
        verbose_name = "Produto"
        verbose_name_plural = "Produtos"
        indexes = [
            models.Index(fields=['produto_estabelecimento']),
            models.Index(fields=['produto_tipo']),
        ]

    def __str__(self):
        return self.produto_nome
    
class ProdutoForm(forms.ModelForm):
    class Meta:
        model = Produto
        fields = [
            'produto_nome',
            'produto_descricao',
            'produto_preco',
            'produto_tipo',
            'produto_ativo',
            'produto_imagem',
            'produto_tag',
        ]
        widgets = {
            'produto_nome': forms.TextInput(attrs={'class': 'form-control'}),
            'produto_descricao': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
            'produto_preco': forms.TextInput(attrs={'class': 'form-control'}),
            'produto_tipo': forms.Select(attrs={'class': 'form-control'}),
            'produto_ativo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'produto_imagem': forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'produto_tag': forms.TextInput(attrs={'class': 'form-control'}),
        }
    
class TamanhoProduto(models.Model):
    tamanho_produto_produto = models.ForeignKey(Produto, on_delete=models.CASCADE, related_name='tamanhos')
    tamanho_produto_nome = models.CharField(max_length=50)
    tamanho_produto_preco = models.DecimalField(max_digits=6, decimal_places=2)

    class Meta:
        verbose_name = "Tamanho de Produto"
        verbose_name_plural = "Tamanhos de Produto"
        indexes = [
            models.Index(fields=['tamanho_produto_produto']),
        ]

    def __str__(self):
        return f"{self.tamanho_produto_nome} ({self.tamanho_produto_produto.produto_nome})"

class TamanhoProdutoForm(forms.ModelForm):
    class Meta:
        model = TamanhoProduto
        fields = ['tamanho_produto_nome', 'tamanho_produto_preco']
        widgets = {
            'tamanho_produto_nome': forms.TextInput(attrs={'class': 'form-control'}),
            'tamanho_produto_preco': forms.TextInput(attrs={'class': 'form-control'}),
        }

TamanhoProdutoFormSet = inlineformset_factory(
    Produto,
    TamanhoProduto,
    form=TamanhoProdutoForm,
    extra=1,
    can_delete=True
)

class Acrescimo(models.Model):
    acrescimo_nome = models.CharField(max_length=100)
    acrescimo_preco = models.DecimalField(max_digits=10, decimal_places=2)
    acrescimo_tipo = models.ForeignKey(TipoProduto, on_delete=models.CASCADE, related_name='tipo_acrescimo')
    acrescimo_ativo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Acréscimo"
        verbose_name_plural = "Acréscimos"
        indexes = [
            models.Index(fields=['acrescimo_tipo']),
        ]

    def __str__(self):
        return f"{self.acrescimo_nome} (+R$ {self.acrescimo_preco})"
    
class AcrescimoForm(forms.ModelForm):
    class Meta:
        model = Acrescimo
        fields = ['acrescimo_nome', 'acrescimo_preco', 'acrescimo_tipo']
        widgets = {
            'acrescimo_nome': forms.TextInput(attrs={'id': 'acrescimo_nome', 'class': 'form-control', 'required': True}),
            'acrescimo_preco': forms.NumberInput(attrs={'id': 'acrescimo_preco', 'class': 'form-control', 'required': True}),
            'acrescimo_tipo': forms.Select(attrs={'id': 'acrescimo_tipo', 'class': 'form-control', 'required': True}),
        }
    
class Cliente(models.Model):
    cliente_estabelecimento = models.ForeignKey(Estabelecimento, on_delete=models.CASCADE, related_name='cliente')
    cliente_nome = models.CharField(max_length=255)
    cliente_telefone = models.CharField(max_length=20)
    cliente_rua = models.CharField(max_length=255)
    cliente_bairro = models.CharField(max_length=255)
    cliente_numero = models.CharField(max_length=10)
    cliente_complemento = models.CharField(max_length=100, blank=True, null=True)
    cliente_taxa_entrega = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    class Meta:
        verbose_name = "Cliente"
        verbose_name_plural = "Clientes"
        indexes = [
            models.Index(fields=['cliente_estabelecimento']),
        ]
        unique_together = [['cliente_estabelecimento', 'cliente_telefone']]

    def __str__(self):
        return self.cliente_nome
    
class FormasDePagamento(models.Model):
    forma_pagamento_estabelecimento = models.ForeignKey(Estabelecimento, on_delete=models.CASCADE, related_name='forma_pagamento')
    forma_pagamento_nome = models.CharField(max_length=50)

    class Meta:
        verbose_name = "Forma de Pagamento"
        verbose_name_plural = "Formas de Pagamento"

    def __str__(self):
        return self.forma_pagamento_nome
    
class Pedido(models.Model):

    STATUS_CHOICES = (
        ('pending', 'Pendente'),
        ('prepary', 'Em Preparo'),
        ('ready', 'Pronto'),
        ('delivery', 'Em Entrega'),
        ('completed', 'Concluído'),
        ('canceled', "Cancelado")
    )

    TIPO_PEDIDO_CHOICES = (
        ('delivery', 'Delivery'),
        ('retirada', 'Retirada'),
    )

    pedido_estabelecimento = models.ForeignKey(Estabelecimento, on_delete=models.CASCADE, related_name='pedido')
    pedido_cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE)
    pedido_data = models.DateTimeField(auto_now_add=True)
    pedido_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    pedido_tipo_entrega = models.CharField(max_length=20, choices=TIPO_PEDIDO_CHOICES, default='delivery')
    pedido_observacao = models.TextField(blank=True, null=True)
    pedido_valor_total = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    pedido_forma_pagamento = models.ForeignKey(FormasDePagamento, on_delete=models.CASCADE, blank=False, null=False)
    pedido_troco = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)  
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def calcular_valor_total(self):
        itens = ItensPedido.objects.filter(itens_pedido_pedido=self).prefetch_related('itens_pedido_acrescimos')
        total = sum(item.itens_pedido_preco_final for item in itens)
        self.pedido_valor_total = total
        self.save()

    def __str__(self):
        return f'Pedido {self.id}'
    
class ItensPedido(models.Model):
    itens_pedido_estabelecimento = models.ForeignKey(Estabelecimento, on_delete=models.CASCADE, related_name='itens_pedido')
    itens_pedido_pedido = models.ForeignKey(Pedido, on_delete=models.CASCADE, related_name='itens')
    itens_pedido_produto = models.ForeignKey(Produto, on_delete=models.CASCADE)
    itens_pedido_tamanho = models.ForeignKey(
        'TamanhoProduto', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='itens'
    )
    itens_pedido_quantidade = models.PositiveIntegerField()
    itens_pedido_preco_unitario = models.DecimalField(max_digits=10, decimal_places=2)
    itens_pedido_acrescimos = models.ManyToManyField(Acrescimo, blank=True)
    itens_pedido_preco_final = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)

    def calcular_preco_final(self):
        # Calcula o preço por unidade (preço unitário + acréscimos)
        preco_por_unidade = self.itens_pedido_preco_unitario
        for acrescimo in self.itens_pedido_acrescimos.all():
            preco_por_unidade += Decimal(str(acrescimo.acrescimo_preco))  # Converte para Decimal
        # Multiplica pelo quantidade
        preco_final = preco_por_unidade * self.itens_pedido_quantidade
        self.itens_pedido_preco_final = preco_final
        self.save()

    class Meta:
        verbose_name = "Item de Pedido"
        verbose_name_plural = "Itens de Pedido"
        indexes = [
            models.Index(fields=['itens_pedido_pedido']),
            models.Index(fields=['itens_pedido_produto']),
            models.Index(fields=['itens_pedido_tamanho']),
        ]

    def __str__(self):
        return f'Item {self.id}'

class Promocao(models.Model):
    promocao_estabelecimento = models.ForeignKey('Estabelecimento', on_delete=models.CASCADE, related_name='promoco7630es')
    promocao_image = models.ImageField(upload_to='delivery/imgs', blank=True, null=True)
    promocao_nome = models.CharField(max_length=100)
    promocao_descricao = models.TextField(blank=True, null=True)
    promocao_preco = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    promocao_ativo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Promoção"
        verbose_name_plural = "Promoções"

    def __str__(self):
        return self.promocao_nome

class PromocaoForm(forms.ModelForm):
    class Meta:
        model = Promocao
        fields = ['promocao_estabelecimento', 'promocao_image', 'promocao_nome', 'promocao_descricao', 'promocao_preco', 'promocao_ativo']
    
class ItensPromocao(models.Model):
    promocao = models.ForeignKey('Promocao', on_delete=models.CASCADE, related_name='itens_fixos')
    produto = models.ForeignKey('Produto', on_delete=models.CASCADE, related_name='itens_promocao')
    quantidade = models.PositiveIntegerField(default=1)

    def __str__(self):
        return f"{self.produto.produto_nome} - {self.quantidade}"
    
class ItensPromocaoForm(forms.ModelForm):
    class Meta:
        model = ItensPromocao
        fields = ['produto', 'quantidade']
    
class GrupoItensPromocao(models.Model):
    promocao = models.ForeignKey('Promocao', on_delete=models.CASCADE, related_name='grupos_itens')
    nome = models.CharField(max_length=100)  # Ex.: "Refrigerante 1", "Acompanhamento"
    quantidade_selecionavel = models.PositiveIntegerField(default=1)  # Quantos itens o cliente deve escolher
    itens = models.ManyToManyField('Produto', related_name='grupos_promocao')  # Opções disponíveis no grupo

    def __str__(self):
        return f"{self.nome} ({self.promocao.promocao_nome})"
    
class GrupoItensPromocaoForm(forms.ModelForm):
    itens = forms.ModelMultipleChoiceField(queryset=Produto.objects.all())

    class Meta:
        model = GrupoItensPromocao
        fields = ['nome', 'quantidade_selecionavel', 'itens']