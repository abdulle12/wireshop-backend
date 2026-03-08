# shop/views.py
import json
import random
from django.conf import settings
from django.core.files.storage import default_storage
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from .models import Shop, Product, Category
from .serializers import ProductSerializer, ShopSerializer, PublicProductSerializer


class ShopListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        shops = Shop.objects.filter(owner=request.user).order_by('-created_at')
        return Response(ShopSerializer(shops, many=True, context={'request': request}).data)

    def post(self, request):
        serializer = ShopSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            serializer.save(owner=request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ShopDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get_object(self, request, pk):
        try:
            return Shop.objects.get(pk=pk, owner=request.user)
        except Shop.DoesNotExist:
            return None

    def get(self, request, pk):
        shop = self.get_object(request, pk)
        if not shop:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(ShopSerializer(shop, context={'request': request}).data)

    def patch(self, request, pk):
        shop = self.get_object(request, pk)
        if not shop:
            return Response(status=status.HTTP_404_NOT_FOUND)
        serializer = ShopSerializer(shop, data=request.data, partial=True, context={'request': request})
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk):
        shop = self.get_object(request, pk)
        if not shop:
            return Response(status=status.HTTP_404_NOT_FOUND)
        shop.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProductListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, shop_id):
        try:
            shop = Shop.objects.get(pk=shop_id, owner=request.user)
        except Shop.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        products = shop.products.all().order_by('-created_at')
        return Response(ProductSerializer(products, many=True, context={'request': request}).data)

    def post(self, request, shop_id):
        try:
            shop = Shop.objects.get(pk=shop_id, owner=request.user)
        except Shop.DoesNotExist:
            return Response({'detail': 'Shop not found.'}, status=404)

        category_name = request.data.get('category')
        category_id   = None
        if category_name:
            cat_obj, _ = Category.objects.get_or_create(
                name=category_name,
                defaults={'slug': category_name.lower().replace(' ', '-')}
            )
            category_id = cat_obj.id

        image_paths = []
        for img in request.FILES.getlist('images'):
            path = default_storage.save(f'products/{img.name}', img)
            image_paths.append(f"{settings.MEDIA_URL}{path}")

        data = {
            'title':         request.data.get('title'),
            'description':   request.data.get('description'),
            'category':      category_id,
            'price':         request.data.get('price'),
            'stock':         request.data.get('stock'),
            'delivery_time': request.data.get('delivery_time', ''),
            'attributes':    json.loads(request.data.get('attributes', '[]')),
            'images':        image_paths,
        }

        serializer = ProductSerializer(data=data, context={'request': request})
        if serializer.is_valid():
            serializer.save(shop=shop)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class PublicProductFeedView(APIView):
    permission_classes = [AllowAny]
    PAGE_SIZE = 50

    def get(self, request):
        category = request.query_params.get('category', '').strip().lower()
        page     = int(request.query_params.get('page', 1))

        qs = Product.objects.select_related('shop', 'category').order_by('-created_at')

        if request.user and request.user.is_authenticated:
            qs = qs.exclude(shop__owner=request.user)

        if category and category != 'all':
            qs = qs.filter(category__name__iexact=category)

        total    = qs.count()
        offset   = (page - 1) * self.PAGE_SIZE
        products = list(qs[offset: offset + self.PAGE_SIZE])
        random.shuffle(products)

        return Response({
            'results': PublicProductSerializer(products, many=True, context={'request': request}).data,
            'page':    page,
            'count':   total,
        })


class PublicCategoryListView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        cats = (
            Product.objects
            .filter(category__isnull=False)
            .values_list('category__name', flat=True)
            .distinct()
        )
        result = sorted(set(c.lower() for c in cats if c))
        return Response(result)


class PublicProductDetailView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, slug):
        try:
            product = Product.objects.select_related('shop', 'category').get(slug=slug)
        except Product.DoesNotExist:
            return Response({'detail': 'Product not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(PublicProductSerializer(product, context={'request': request}).data)


class ShopFollowView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, slug):
        from .models import ShopFollower, ShopToShopFollower

        try:
            target_shop = Shop.objects.get(slug=slug)
        except Shop.DoesNotExist:
            return Response({'detail': 'Shop not found.'}, status=404)

        as_shop_id = request.data.get('as_shop')

        if as_shop_id:
            try:
                follower_shop = Shop.objects.get(pk=as_shop_id, owner=request.user)
            except Shop.DoesNotExist:
                return Response({'detail': 'Your shop not found.'}, status=404)

            if follower_shop == target_shop:
                return Response({'detail': 'A shop cannot follow itself.'}, status=400)

            existing = ShopToShopFollower.objects.filter(
                following=target_shop, follower_shop=follower_shop
            ).first()

            if existing:
                existing.delete()
                following = False
            else:
                ShopToShopFollower.objects.create(
                    following=target_shop, follower_shop=follower_shop
                )
                following = True

        else:
            if target_shop.owner == request.user:
                return Response({'detail': 'You cannot follow your own shop.'}, status=400)

            existing = ShopFollower.objects.filter(
                shop=target_shop, user=request.user
            ).first()

            if existing:
                existing.delete()
                following = False
            else:
                ShopFollower.objects.create(shop=target_shop, user=request.user)
                following = True

        total = target_shop.followers.count() + target_shop.shop_followers.count()

        return Response({
            'following':      following,
            'follower_count': total,
        })


class PublicShopDetailView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, slug):
        from .models import ShopFollower, ShopToShopFollower

        try:
            shop = Shop.objects.get(slug=slug)
        except Shop.DoesNotExist:
            return Response({'detail': 'Shop not found.'}, status=404)

        data = ShopSerializer(shop, context={'request': request}).data
        data['follower_count'] = (
            shop.followers.count() +
            shop.shop_followers.count()
        )

        if request.user and request.user.is_authenticated:
            as_shop_id = request.query_params.get('as_shop')
            if as_shop_id:
                try:
                    viewer_shop = Shop.objects.get(pk=as_shop_id, owner=request.user)
                    data['is_following'] = ShopToShopFollower.objects.filter(
                        following=shop, follower_shop=viewer_shop
                    ).exists()
                except Shop.DoesNotExist:
                    data['is_following'] = False
            else:
                data['is_following'] = ShopFollower.objects.filter(
                    shop=shop, user=request.user
                ).exists()
            data['is_owner'] = (shop.owner == request.user)
        else:
            data['is_following'] = False
            data['is_owner']     = False

        return Response(data)


class PublicShopProductsView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, slug):
        try:
            shop = Shop.objects.get(slug=slug)
        except Shop.DoesNotExist:
            return Response({'detail': 'Shop not found.'}, status=status.HTTP_404_NOT_FOUND)

        category = request.query_params.get('category', '').strip().lower()
        qs = shop.products.select_related('category').order_by('-created_at')
        if category and category != 'all':
            qs = qs.filter(category__name__iexact=category)
        return Response(PublicProductSerializer(qs, many=True, context={'request': request}).data)


class FollowingFeedView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .models import ShopFollower, ShopToShopFollower

        as_shop_id = request.query_params.get('as_shop')
        category   = request.query_params.get('category', '').strip().lower()
        page       = int(request.query_params.get('page', 1))
        page_size  = 12

        if as_shop_id:
            try:
                viewer_shop  = Shop.objects.get(pk=as_shop_id, owner=request.user)
                followed_ids = list(ShopToShopFollower.objects.filter(
                    follower_shop=viewer_shop
                ).values_list('following_id', flat=True))
            except Shop.DoesNotExist:
                return Response({'results': [], 'has_next': False})
        else:
            followed_ids = list(ShopFollower.objects.filter(
                user=request.user
            ).values_list('shop_id', flat=True))

        if not followed_ids:
            return Response({'results': [], 'has_next': False})

        qs = Product.objects.filter(
            shop_id__in=followed_ids
        ).select_related('shop', 'category').order_by('-created_at')

        if category and category != 'all':
            qs = qs.filter(category__name__iexact=category)

        total    = qs.count()
        all_ids  = list(qs.values_list('id', flat=True))
        random.shuffle(all_ids)

        start    = (page - 1) * page_size
        end      = start + page_size
        page_ids = all_ids[start:end]
        has_next = end < total

        products_map = {
            p.id: p for p in Product.objects.filter(
                id__in=page_ids
            ).select_related('shop', 'category')
        }
        products = [products_map[pid] for pid in page_ids if pid in products_map]

        return Response({
            'results':  PublicProductSerializer(products, many=True, context={'request': request}).data,
            'has_next': has_next,
        })


class FollowingCategoryListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .models import ShopFollower, ShopToShopFollower

        as_shop_id = request.query_params.get('as_shop')

        if as_shop_id:
            try:
                viewer_shop  = Shop.objects.get(pk=as_shop_id, owner=request.user)
                followed_ids = list(ShopToShopFollower.objects.filter(
                    follower_shop=viewer_shop
                ).values_list('following_id', flat=True))
            except Shop.DoesNotExist:
                return Response([])
        else:
            followed_ids = list(ShopFollower.objects.filter(
                user=request.user
            ).values_list('shop_id', flat=True))

        if not followed_ids:
            return Response([])

        # Query through Product directly — avoids Category reverse relation name issues
        cats = (
            Product.objects
            .filter(shop_id__in=followed_ids, category__isnull=False)
            .values_list('category__name', flat=True)
            .distinct()
        )

        result = sorted(set(c.lower() for c in cats if c))
        return Response(result)
class FollowingShopsListView(APIView):
    """
    GET /api/feed/following/shops/
    Returns the list of shops the current user follows (for sidebar display).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .models import ShopFollower

        followed = ShopFollower.objects.filter(
            user=request.user
        ).select_related('shop').order_by('shop__shop_name')

        data = [
            {
                'id':            s.shop.id,
                'shop_name':     s.shop.shop_name,
                'shop_category': s.shop.shop_category,
                'avatar':        request.build_absolute_uri(s.shop.avatar.url) if s.shop.avatar else None,
                'slug':          s.shop.slug,
            }
            for s in followed
        ]
        return Response(data)    