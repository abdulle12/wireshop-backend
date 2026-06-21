# shop/serializers.py
from rest_framework import serializers
from .models import Product, Shop, Category


class ShopSerializer(serializers.ModelSerializer):
    class Meta:
        model            = Shop
        fields           = '__all__'
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
        model            = Product
        fields           = '__all__'
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
    shop_name   = serializers.CharField(source='shop.shop_name',   read_only=True)
    shop_slug   = serializers.SlugField(source='shop.slug',        read_only=True)
    shop_avatar = serializers.SerializerMethodField()
    shop_id     = serializers.IntegerField(source='shop.id',       read_only=True)
    seller_id   = serializers.IntegerField(source='shop.owner.id', read_only=True)
    category    = serializers.SerializerMethodField()

    class Meta:
        model  = Product
        fields = [
            'id', 'slug',
            'shop_id', 'shop_slug', 'shop_name', 'shop_avatar',
            'seller_id',
            'title', 'description',
            'price', 'stock', 'delivery_time',
            'buy_count',
            'share_count',
            'attributes', 'images',
            'category',
            'created_at',
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


class ShopReviewSerializer(serializers.ModelSerializer):
    reviewer_name        = serializers.SerializerMethodField()
    reviewer_avatar      = serializers.SerializerMethodField()
    reviewer_shop_name   = serializers.SerializerMethodField()
    reviewer_shop_avatar = serializers.SerializerMethodField()
    reviewer_shop_slug   = serializers.SerializerMethodField()
    helpful_count        = serializers.SerializerMethodField()
    user_found_helpful   = serializers.SerializerMethodField()

    class Meta:
        from .models import ShopReview
        model  = ShopReview
        fields = [
            'id', 'rating', 'title', 'comment', 'created_at',
            'reviewer_name', 'reviewer_avatar',
            'reviewer_shop_name', 'reviewer_shop_avatar', 'reviewer_shop_slug',
            'helpful_count', 'user_found_helpful',
        ]

    def _reviewer_info(self, obj):
        request = self.context.get('request')
        if obj.reviewer_shop:
            s      = obj.reviewer_shop
            avatar = request.build_absolute_uri(s.avatar.url) if (s.avatar and request) else None
            return s.shop_name, avatar, s.shop_name, avatar, s.slug
        u = obj.reviewer
        # Build full name the same way the notification system does:
        #   1. full_name (custom field set at signup)
        #   2. first_name + last_name joined
        #   3. email prefix — never raw username/email which may be a Gmail address
        full = getattr(u, 'full_name', '') or ''
        full = full.strip()
        if not full:
            first = (u.first_name or '').strip()
            last  = (u.last_name  or '').strip()
            full  = ' '.join(p for p in [first, last] if p)
        if not full:
            full = (u.email or '').split('@')[0].replace('.', ' ').replace('_', ' ').title()
        # Avatar: try userprofile.profile_picture
        avatar = None
        try:
            photo = u.userprofile.profile_picture
            if photo:
                url = photo.url if hasattr(photo, 'url') else str(photo)
                avatar = request.build_absolute_uri(url) if request else url
        except Exception:
            pass
        return full, avatar, None, None, None

    def get_reviewer_name(self, obj):        return self._reviewer_info(obj)[0]
    def get_reviewer_avatar(self, obj):      return self._reviewer_info(obj)[1]
    def get_reviewer_shop_name(self, obj):   return self._reviewer_info(obj)[2]
    def get_reviewer_shop_avatar(self, obj): return self._reviewer_info(obj)[3]
    def get_reviewer_shop_slug(self, obj):   return self._reviewer_info(obj)[4]

    def get_helpful_count(self, obj):
        return obj.helpful_votes.count()

    def get_user_found_helpful(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        return obj.helpful_votes.filter(user=request.user).exists()


class ProductReviewSerializer(serializers.ModelSerializer):
    reviewer_name        = serializers.SerializerMethodField()
    reviewer_avatar      = serializers.SerializerMethodField()
    reviewer_shop_name   = serializers.SerializerMethodField()
    reviewer_shop_avatar = serializers.SerializerMethodField()
    reviewer_shop_slug   = serializers.SerializerMethodField()
    helpful_count        = serializers.SerializerMethodField()
    user_found_helpful   = serializers.SerializerMethodField()

    class Meta:
        from .models import ProductReview
        model  = ProductReview
        fields = [
            'id', 'rating', 'title', 'comment', 'created_at',
            'reviewer_name', 'reviewer_avatar',
            'reviewer_shop_name', 'reviewer_shop_avatar', 'reviewer_shop_slug',
            'helpful_count', 'user_found_helpful',
        ]

    def _reviewer_info(self, obj):
        request = self.context.get('request')
        if obj.reviewer_shop:
            s      = obj.reviewer_shop
            avatar = request.build_absolute_uri(s.avatar.url) if (s.avatar and request) else None
            return s.shop_name, avatar, s.shop_name, avatar, s.slug
        u = obj.reviewer
        # Priority: full_name → first+last → email prefix (never raw email)
        full = getattr(u, 'full_name', '') or ''
        full = full.strip()
        if not full:
            first = (u.first_name or '').strip()
            last  = (u.last_name  or '').strip()
            full  = ' '.join(p for p in [first, last] if p)
        if not full:
            full = (u.email or '').split('@')[0].replace('.', ' ').replace('_', ' ').title()
        avatar = None
        try:
            photo = u.userprofile.profile_picture
            if photo:
                url = photo.url if hasattr(photo, 'url') else str(photo)
                avatar = request.build_absolute_uri(url) if request else url
        except Exception:
            pass
        return full, avatar, None, None, None

    def get_reviewer_name(self, obj):        return self._reviewer_info(obj)[0]
    def get_reviewer_avatar(self, obj):      return self._reviewer_info(obj)[1]
    def get_reviewer_shop_name(self, obj):   return self._reviewer_info(obj)[2]
    def get_reviewer_shop_avatar(self, obj): return self._reviewer_info(obj)[3]
    def get_reviewer_shop_slug(self, obj):   return self._reviewer_info(obj)[4]

    def get_helpful_count(self, obj):
        return obj.helpful_votes.count()

    def get_user_found_helpful(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        return obj.helpful_votes.filter(user=request.user).exists()