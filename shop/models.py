# shop/models.py
from django.db import models
from django.conf import settings
import re
import secrets


class Shop(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='shops'
    )
    shop_name        = models.CharField(max_length=200)
    shop_category    = models.CharField(max_length=100)
    phone_email      = models.CharField(max_length=200)
    address          = models.TextField()
    description      = models.TextField(blank=True, default='')
    cover_image      = models.ImageField(upload_to='shops/covers/', blank=True, null=True)
    avatar           = models.ImageField(upload_to='shops/avatars/', blank=True, null=True)
    shipping_zones   = models.CharField(max_length=200, blank=True)
    shipping_methods = models.CharField(max_length=100)
    shipping_rules   = models.CharField(max_length=200)
    currency         = models.CharField(max_length=10)
    paypal_connected = models.BooleanField(default=False)
    bank_connected   = models.BooleanField(default=False)
    agreed_to_terms  = models.BooleanField(default=False)
    created_at       = models.DateTimeField(auto_now_add=True)
    updated_at       = models.DateTimeField(auto_now=True)
    slug = models.SlugField(max_length=150, unique=True, blank=True, null=True)

    def _generate_slug(self):
        import re, secrets
        base = re.sub(r'[^a-z0-9\s-]', '', self.shop_name.lower())
        base = re.sub(r'[\s-]+', '-', base).strip('-')[:60].rstrip('-')
        return f"{base}-{secrets.token_hex(4)}"

    def save(self, *args, **kwargs):
        if not self.slug:
            slug = self._generate_slug()
            while Shop.objects.filter(slug=slug).exists():
                slug = self._generate_slug()
            self.slug = slug
        super().save(*args, **kwargs)

    class Meta:
        verbose_name        = "Shop"
        verbose_name_plural = "Shops"

    def __str__(self):
        return self.shop_name


class Category(models.Model):
    name = models.CharField(max_length=120)
    slug = models.SlugField(unique=True)

    class Meta:
        verbose_name        = "Category"
        verbose_name_plural = "Categories"

    def __str__(self):
        return self.name


class Product(models.Model):
    shop          = models.ForeignKey('Shop', on_delete=models.CASCADE, related_name='products')
    category      = models.ForeignKey('Category', on_delete=models.SET_NULL, null=True, blank=True)
    title         = models.CharField(max_length=255)
    description   = models.TextField(blank=True)
    price         = models.DecimalField(max_digits=10, decimal_places=2)
    stock         = models.PositiveIntegerField(default=0)
    delivery_time = models.CharField(max_length=100, blank=True)
    buy_count     = models.PositiveIntegerField(default=0)
    share_count   = models.PositiveIntegerField(default=0)
    attributes    = models.JSONField(default=list, blank=True)
    images        = models.JSONField(default=list, blank=True)
    slug          = models.SlugField(max_length=120, unique=True, blank=True, null=True)
    created_at    = models.DateTimeField(auto_now_add=True)

    def _generate_slug(self):
        base = re.sub(r'[^a-z0-9\s-]', '', self.title.lower())
        base = re.sub(r'[\s-]+', '-', base).strip('-')[:50].rstrip('-')
        suffix = secrets.token_hex(4)
        return f"{base}-{suffix}"

    def save(self, *args, **kwargs):
        if not self.slug:
            slug = self._generate_slug()
            while Product.objects.filter(slug=slug).exists():
                slug = self._generate_slug()
            self.slug = slug
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title


class ShopFollower(models.Model):
    shop       = models.ForeignKey('Shop', on_delete=models.CASCADE, related_name='followers')
    user       = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='following_shops')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('shop', 'user')

    def __str__(self):
        return f"{self.user} follows {self.shop}"


class ShopToShopFollower(models.Model):
    following     = models.ForeignKey(
        'Shop', on_delete=models.CASCADE, related_name='shop_followers'
    )
    follower_shop = models.ForeignKey(
        'Shop', on_delete=models.CASCADE, related_name='shops_following'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('following', 'follower_shop')

    def __str__(self):
        return f"{self.follower_shop} follows {self.following}"


class ShopReview(models.Model):
    shop          = models.ForeignKey(
        'Shop', on_delete=models.CASCADE, related_name='reviews'
    )
    reviewer      = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='shop_reviews'
    )
    reviewer_shop = models.ForeignKey(
        'Shop', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='reviews_given'
    )
    rating        = models.PositiveSmallIntegerField()
    title         = models.CharField(max_length=120, blank=True)
    comment       = models.TextField()
    created_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('shop', 'reviewer', 'reviewer_shop')
        ordering        = ['-created_at']

    def __str__(self):
        return f"{self.reviewer} → {self.shop} ({self.rating}★)"


class ReviewHelpful(models.Model):
    review     = models.ForeignKey(
        'ShopReview', on_delete=models.CASCADE, related_name='helpful_votes'
    )
    user       = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('review', 'user')


# ── Product (item) reviews ────────────────────────────────────────────────────

class ProductReview(models.Model):
    """
    A buyer's review of a specific product, tied to the escrow transaction
    that proved they actually purchased it.

    Rules enforced at the view level:
      - Only buyers whose transaction reached STATUS_RELEASED can review.
      - One review per (transaction) — can't double-review the same purchase.
      - reviewer_shop is set when the buyer was browsing as a shop at checkout.
    """
    product     = models.ForeignKey(
        'Product', on_delete=models.CASCADE, related_name='reviews'
    )
    transaction = models.OneToOneField(              # one review per purchase
        'escrow_app.EscrowTransaction',
        on_delete=models.CASCADE,
        related_name='product_review',
        null=True, blank=True,                       # null = review submitted without tx ref (admin use)
    )
    reviewer      = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='product_reviews'
    )
    reviewer_shop = models.ForeignKey(               # set when buyer checked out AS a shop
        'Shop', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='product_reviews_given'
    )
    rating    = models.PositiveSmallIntegerField()   # 1 – 5
    title     = models.CharField(max_length=120, blank=True)
    comment   = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        # One review per buyer (personal or shop identity) per product
        unique_together = ('product', 'reviewer', 'reviewer_shop')

    def __str__(self):
        return f"{self.reviewer} → {self.product} ({self.rating}★)"


class ProductReviewHelpful(models.Model):
    """Tracks which users found a product review helpful (toggle)."""
    review = models.ForeignKey(
        'ProductReview', on_delete=models.CASCADE, related_name='helpful_votes'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('review', 'user')