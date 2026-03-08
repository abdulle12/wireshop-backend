# fix_slugs.py — place in same folder as manage.py
# Run with: python manage.py runscript fix_slugs
# OR just run directly: python fix_slugs.py

import re
import secrets
import django
import os
import sys

# Add your project to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')  # change 'config' to your project name
django.setup()

from store.models import Product  # change 'store' if your app name is different

def generate_slug(title):
    base = re.sub(r'[^a-z0-9\s-]', '', title.lower())
    base = re.sub(r'[\s-]+', '-', base).strip('-')[:50].rstrip('-')
    return f"{base}-{secrets.token_hex(4)}"

used = set()

products = list(Product.objects.filter(slug='')) + list(Product.objects.filter(slug__isnull=True))

for product in products:
    slug = generate_slug(product.title)
    while slug in used or Product.objects.filter(slug=slug).exists():
        slug = generate_slug(product.title)
    used.add(slug)
    product.slug = slug
    product.save(update_fields=['slug'])
    print(f"OK: {product.title[:40]} -> {slug}")

print(f"\nDone. Filled {len(used)} slugs.")