# shop/serializers.py
from rest_framework import serializers
from .models import Product, Shop, Category


class ShopSerializer(serializers.ModelSerializer):
    class Meta:
        model        = Shop
        fields       = '__all__'
        read_only_fields = ('owner', 'created_at', 'updated_at')

    def to_representation(self, instance):
        data    = super().to_representation(instance)
        request = self.context.get('request')
        for field in ['cover_image', 'avatar']:
            if data.get(field) and request:
                data[field] = request.build_absolute_uri(data[field])
        return data


class ProductSerializer(serializers.ModelSerializer):
    shop_name = serializers.CharField(source='shop.shop_name', read_only=True)
    category  = serializers.PrimaryKeyRelatedField(
        queryset=Category.objects.all(), required=False, allow_null=True
    )

    class Meta:
        model        = Product
        fields       = '__all__'
        read_only_fields = ('shop', 'created_at', 'shop_name')

    def to_representation(self, instance):
        data    = super().to_representation(instance)
        request = self.context.get('request')
        if instance.category:
            data['category'] = instance.category.name
        if request and instance.images:
            data['images'] = [
                request.build_absolute_uri(img) if not img.startswith('http') else img
                for img in instance.images
            ]
        return data


class PublicProductSerializer(serializers.ModelSerializer):
    shop_name   = serializers.CharField(source='shop.shop_name', read_only=True)
    shop_slug = serializers.SlugField(source='shop.slug', read_only=True)
    shop_avatar = serializers.SerializerMethodField()
    shop_id     = serializers.IntegerField(source='shop.id', read_only=True)
    category    = serializers.SerializerMethodField()

    class Meta:
        model  = Product
        fields = [
            'id', 'slug', 'shop_id', 'shop_slug', 'title', 'description', 'price', 'stock',
            'delivery_time', 'attributes', 'images',
            'category', 'shop_name', 'shop_avatar', 'created_at',
        ]

    def get_shop_avatar(self, obj):
        request = self.context.get('request')
        if obj.shop.avatar and request:
            return request.build_absolute_uri(obj.shop.avatar.url)
        return None

    def get_category(self, obj):
        return obj.category.name.lower() if obj.category else None

    def to_representation(self, instance):
        data    = super().to_representation(instance)
        request = self.context.get('request')
        if request and instance.images:
            data['images'] = [
                request.build_absolute_uri(img) if not img.startswith('http') else img
                for img in instance.images
            ]
        return data