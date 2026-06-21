# shop/views.py
import json
import random
from django.conf import settings
from django.core.files.storage import default_storage
from django.db.models import Avg, Count
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from .models import Shop, Product, Category, ShopReview
from .serializers import ProductSerializer, ShopSerializer, PublicProductSerializer, ShopReviewSerializer


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


class ProductDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get_object(self, shop_id, pk, user):
        try:
            shop = Shop.objects.get(pk=shop_id, owner=user)
            return Product.objects.get(pk=pk, shop=shop)
        except (Shop.DoesNotExist, Product.DoesNotExist):
            return None

    def patch(self, request, shop_id, pk):
        product = self.get_object(shop_id, pk, request.user)
        if not product:
            return Response(status=404)

        category_name = request.data.get('category')
        category_id   = product.category_id
        if category_name:
            cat_obj, _ = Category.objects.get_or_create(
                name=category_name,
                defaults={'slug': category_name.lower().replace(' ', '-')}
            )
            category_id = cat_obj.id

        new_images = request.FILES.getlist('images')
        if new_images:
            existing  = product.images or []
            new_paths = []
            for img in new_images:
                path = default_storage.save(f'products/{img.name}', img)
                new_paths.append(f"{settings.MEDIA_URL}{path}")
            images = existing + new_paths
        else:
            images = product.images or []

        raw_attrs = request.data.get('attributes')
        if raw_attrs and isinstance(raw_attrs, str):
            try:
                attributes = json.loads(raw_attrs)
            except Exception:
                attributes = product.attributes
        else:
            attributes = product.attributes

        data = {
            'title':         request.data.get('title',         product.title),
            'description':   request.data.get('description',   product.description),
            'category':      category_id,
            'price':         request.data.get('price',         product.price),
            'stock':         request.data.get('stock',         product.stock),
            'delivery_time': request.data.get('delivery_time', product.delivery_time),
            'attributes':    attributes,
            'images':        images,
        }

        serializer = ProductSerializer(product, data=data, partial=True, context={'request': request})
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=400)

    def delete(self, request, shop_id, pk):
        product = self.get_object(shop_id, pk, request.user)
        if not product:
            return Response(status=404)
        product.delete()
        return Response(status=204)


class PublicProductFeedView(APIView):
    permission_classes = [AllowAny]
    PAGE_SIZE = 50

    def get(self, request):
        from django.db.models import Q
        category = request.query_params.get('category', '').strip().lower()
        page     = int(request.query_params.get('page', 1))
        q        = request.query_params.get('q', '').strip()

        qs = Product.objects.select_related(
            'shop', 'shop__owner', 'category'
        ).order_by('-created_at')

        if request.user and request.user.is_authenticated:
            qs = qs.exclude(shop__owner=request.user)

        if category and category != 'all':
            qs = qs.filter(category__name__iexact=category)

        if q:
            words = q.split()
            for word in words:
                qs = qs.filter(
                    Q(title__icontains=word) |
                    Q(description__icontains=word) |
                    Q(attributes__icontains=word)
                )
            qs = qs.distinct()

        total    = qs.count()
        offset   = (page - 1) * self.PAGE_SIZE
        products = list(qs[offset: offset + self.PAGE_SIZE])

        if not q:
            random.shuffle(products)

        return Response({
            'results':  PublicProductSerializer(products, many=True, context={"request": request}).data,
            'page':     page,
            'count':    total,
            'has_next': (offset + self.PAGE_SIZE) < total,
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
            product = Product.objects.select_related(
                'shop', 'shop__owner', 'category'
            ).get(slug=slug)
        except Product.DoesNotExist:
            return Response({'detail': 'Product not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(PublicProductSerializer(product, context={'request': request}).data)



class ShareProductView(APIView):
    """
    POST /api/products/<slug>/share/

    Atomically increments share_count by 1.
    No authentication required — anyone sharing increments the count,
    exactly like TikTok/Instagram share counts.
    Returns { share_count: <new_total> }
    """
    permission_classes = []   # public — no auth needed

    def post(self, request, slug):
        from django.db.models import F
        updated = Product.objects.filter(slug=slug).update(
            share_count=F('share_count') + 1
        )
        if not updated:
            return Response({'detail': 'Product not found.'}, status=404)
        share_count = Product.objects.filter(slug=slug).values_list('share_count', flat=True).first()
        return Response({'share_count': share_count})


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

        stats = shop.reviews.aggregate(avg=Avg('rating'), total=Count('id'))
        data['avg_rating']   = round(stats['avg'] or 0, 1)
        data['review_count'] = stats['total']

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
        qs = shop.products.select_related(
            'shop', 'shop__owner', 'category'
        ).order_by('-created_at')
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
        ).select_related('shop', 'shop__owner', 'category').order_by('-created_at')

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
            ).select_related('shop', 'shop__owner', 'category')
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
    GET /api/feed/following/shops/?as_shop=<id>

    Personal mode  (?as_shop absent): shops followed by request.user personally
                                       via ShopFollower.
    Shop mode      (?as_shop=<id>):   shops followed by that shop identity
                                       via ShopToShopFollower.

    The two sets are completely independent — joining while in personal mode
    does NOT affect the shop's following list and vice versa.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .models import ShopFollower, ShopToShopFollower

        as_shop_id = request.query_params.get('as_shop')

        if as_shop_id:
            # ── Shop mode: shops this shop account follows ───────────────────
            try:
                viewer_shop = Shop.objects.get(pk=as_shop_id, owner=request.user)
            except Shop.DoesNotExist:
                return Response([])

            followed = ShopToShopFollower.objects.filter(
                follower_shop=viewer_shop
            ).select_related('following').order_by('following__shop_name')

            data = [
                {
                    'id':            s.following.id,
                    'shop_name':     s.following.shop_name,
                    'shop_category': s.following.shop_category,
                    'avatar':        request.build_absolute_uri(s.following.avatar.url)
                                     if s.following.avatar else None,
                    'slug':          s.following.slug,
                }
                for s in followed
            ]

        else:
            # ── Personal mode: shops this user personally follows ────────────
            followed = ShopFollower.objects.filter(
                user=request.user
            ).select_related('shop').order_by('shop__shop_name')

            data = [
                {
                    'id':            s.shop.id,
                    'shop_name':     s.shop.shop_name,
                    'shop_category': s.shop.shop_category,
                    'avatar':        request.build_absolute_uri(s.shop.avatar.url)
                                     if s.shop.avatar else None,
                    'slug':          s.shop.slug,
                }
                for s in followed
            ]

        return Response(data)


class ShopReviewListCreateView(APIView):
    """
    GET  /api/shops/public/<slug>/reviews/           list reviews + overall stats
    GET  /api/shops/public/<slug>/reviews/?rating=4  filter by star rating
    POST /api/shops/public/<slug>/reviews/           submit a review (auth required)
    """
    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsAuthenticated()]
        return [AllowAny()]

    def get(self, request, slug):
        try:
            shop = Shop.objects.get(slug=slug)
        except Shop.DoesNotExist:
            return Response({'detail': 'Shop not found.'}, status=404)

        filter_rating = request.query_params.get('rating', '').strip()

        qs = (
            ShopReview.objects
            .filter(shop=shop)
            .select_related('reviewer', 'reviewer_shop')
            .prefetch_related('helpful_votes')
            .order_by('-created_at')
        )

        if filter_rating.isdigit():
            qs = qs.filter(rating=int(filter_rating))

        all_qs    = ShopReview.objects.filter(shop=shop)
        stats     = all_qs.aggregate(avg=Avg('rating'), total=Count('id'))
        breakdown = {
            str(i): all_qs.filter(rating=i).count()
            for i in range(1, 6)
        }

        serializer = ShopReviewSerializer(qs, many=True, context={'request': request})
        return Response({
            'reviews':    serializer.data,
            'avg_rating': round(stats['avg'] or 0, 1),
            'total':      stats['total'],
            'breakdown':  breakdown,
        })

    def post(self, request, slug):
        try:
            shop = Shop.objects.get(slug=slug)
        except Shop.DoesNotExist:
            return Response({'detail': 'Shop not found.'}, status=404)

        if shop.owner == request.user:
            return Response({'detail': 'You cannot review your own shop.'}, status=400)

        reviewer_shop = None
        as_shop_id    = request.data.get('as_shop')
        if as_shop_id:
            try:
                reviewer_shop = Shop.objects.get(pk=as_shop_id, owner=request.user)
            except Shop.DoesNotExist:
                return Response({'detail': 'Invalid shop account.'}, status=400)

        if ShopReview.objects.filter(
            shop=shop, reviewer=request.user, reviewer_shop=reviewer_shop
        ).exists():
            return Response({'detail': 'You have already reviewed this shop.'}, status=400)

        rating  = request.data.get('rating', '')
        title   = request.data.get('title', '').strip()
        comment = request.data.get('comment', '').strip()

        if not str(rating).isdigit() or not (1 <= int(rating) <= 5):
            return Response({'detail': 'Rating must be between 1 and 5.'}, status=400)
        if not comment:
            return Response({'detail': 'Comment is required.'}, status=400)

        review = ShopReview.objects.create(
            shop=shop,
            reviewer=request.user,
            reviewer_shop=reviewer_shop,
            rating=int(rating),
            title=title,
            comment=comment,
        )
        return Response(
            ShopReviewSerializer(review, context={'request': request}).data,
            status=201,
        )


class ShopReviewHelpfulView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        from .models import ReviewHelpful

        try:
            review = ShopReview.objects.get(pk=pk)
        except ShopReview.DoesNotExist:
            return Response({'detail': 'Review not found.'}, status=404)

        obj, created = ReviewHelpful.objects.get_or_create(
            review=review, user=request.user
        )
        if not created:
            obj.delete()
            helpful = False
        else:
            helpful = True

        return Response({
            'helpful':       helpful,
            'helpful_count': review.helpful_votes.count(),
        })


class ProductReviewListCreateView(APIView):
    """
    GET  /api/products/<slug>/reviews/           — list reviews + stats (public)
    GET  /api/products/<slug>/reviews/?rating=4  — filter by star
    POST /api/products/<slug>/reviews/           — submit review (auth required)

    To submit:
      {
        rating:       1–5,
        title:        str (optional),
        comment:      str (required),
        transaction:  <uuid> (required — must be a RELEASED transaction where
                               request.user is the buyer and product matches),
        as_shop:      <int> (optional — shop id if reviewing as a shop)
      }
    """
    from django.db.models import Avg, Count

    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsAuthenticated()]
        return [AllowAny()]

    def get(self, request, slug):
        try:
            product = Product.objects.get(slug=slug)
        except Product.DoesNotExist:
            return Response({'detail': 'Product not found.'}, status=404)

        from .models import ProductReview
        from .serializers import ProductReviewSerializer
        from django.db.models import Avg, Count

        filter_rating = request.query_params.get('rating', '').strip()

        qs = (
            ProductReview.objects
            .filter(product=product)
            .select_related('reviewer', 'reviewer_shop')
            .prefetch_related('helpful_votes')
            .order_by('-created_at')
        )

        if filter_rating.isdigit():
            qs = qs.filter(rating=int(filter_rating))

        all_qs    = ProductReview.objects.filter(product=product)
        stats     = all_qs.aggregate(avg=Avg('rating'), total=Count('id'))
        breakdown = {
            str(i): all_qs.filter(rating=i).count()
            for i in range(1, 6)
        }

        serializer = ProductReviewSerializer(qs, many=True, context={'request': request})
        return Response({
            'reviews':    serializer.data,
            'avg_rating': round(stats['avg'] or 0, 1),
            'total':      stats['total'],
            'breakdown':  breakdown,
        })

    def post(self, request, slug):
        try:
            product = Product.objects.get(slug=slug)
        except Product.DoesNotExist:
            return Response({'detail': 'Product not found.'}, status=404)

        from .models import ProductReview
        from .serializers import ProductReviewSerializer
        from escrow_app.models import EscrowTransaction

        tx_id = request.data.get('transaction')
        if not tx_id:
            return Response({'detail': 'transaction is required.'}, status=400)

        try:
            tx = EscrowTransaction.objects.get(
                pk=tx_id,
                buyer=request.user,
                product=product,
                status=EscrowTransaction.STATUS_RELEASED,
            )
        except EscrowTransaction.DoesNotExist:
            return Response(
                {'detail': 'No completed purchase found for this product.'},
                status=400,
            )

        reviewer_shop = None
        as_shop_id    = request.data.get('as_shop')
        if as_shop_id:
            try:
                reviewer_shop = Shop.objects.get(pk=as_shop_id, owner=request.user)
            except Shop.DoesNotExist:
                return Response({'detail': 'Invalid shop account.'}, status=400)

        if ProductReview.objects.filter(
            product=product, reviewer=request.user, reviewer_shop=reviewer_shop
        ).exists():
            return Response({'detail': 'You have already reviewed this product.'}, status=400)

        rating  = request.data.get('rating', '')
        title   = request.data.get('title', '').strip()
        comment = request.data.get('comment', '').strip()

        if not str(rating).isdigit() or not (1 <= int(rating) <= 5):
            return Response({'detail': 'Rating must be between 1 and 5.'}, status=400)
        if not comment:
            return Response({'detail': 'Comment is required.'}, status=400)

        review = ProductReview.objects.create(
            product       = product,
            transaction   = tx,
            reviewer      = request.user,
            reviewer_shop = reviewer_shop,
            rating        = int(rating),
            title         = title,
            comment       = comment,
        )

        return Response(
            ProductReviewSerializer(review, context={'request': request}).data,
            status=201,
        )


class ProductReviewHelpfulView(APIView):
    """POST /api/products/reviews/<pk>/helpful/ — toggle helpful (auth required)"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        from .models import ProductReview, ProductReviewHelpful

        try:
            review = ProductReview.objects.get(pk=pk)
        except ProductReview.DoesNotExist:
            return Response({'detail': 'Review not found.'}, status=404)

        obj, created = ProductReviewHelpful.objects.get_or_create(
            review=review, user=request.user
        )
        if not created:
            obj.delete()
            helpful = False
        else:
            helpful = True

        return Response({
            'helpful':       helpful,
            'helpful_count': review.helpful_votes.count(),
        })