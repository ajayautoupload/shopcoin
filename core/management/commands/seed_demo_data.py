from datetime import date, timedelta
from io import BytesIO

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from PIL import Image, ImageDraw, ImageFont

from accounts.models import CustomerProfile, ShopkeeperProfile, UserProfile
from offers.models import ShopAd, ShopOffer
from shops.models import Product, Shop

User = get_user_model()
SHOP_SLUG = 'abc-fashion-store'
SHOPKEEPER_USERNAME = 'demo_shopkeeper'

PRODUCTS = [
    ("Men's Cotton Shirt", 'mens-cotton-shirt', 'Shirts', 'M, L, XL', 'Sky blue', 999, 799, 18, 'Soft cotton everyday shirt in a relaxed fit.'),
    ("Men's Casual T-Shirt", 'mens-casual-tshirt', 'T-Shirts', 'S, M, L, XL', 'Forest green', 699, 549, 26, 'Comfortable cotton jersey tee for daily wear.'),
    ("Men's Denim Jeans", 'mens-denim-jeans', 'Jeans', '30, 32, 34, 36', 'Indigo', 1499, 1199, 12, 'Classic straight-fit denim with five pockets.'),
    ("Women's Everyday Kurti", 'womens-everyday-kurti', 'Kurtis', 'S, M, L, XL', 'Marigold', 1299, 999, 15, 'Lightweight printed kurti for everyday comfort.'),
    ("Women's Cotton Top", 'womens-cotton-top', 'Tops', 'S, M, L', 'Rose', 899, 699, 21, 'Breathable cotton top with a clean silhouette.'),
    ("Women's Straight Jeans", 'womens-straight-jeans', 'Jeans', '28, 30, 32, 34', 'Dark indigo', 1599, 1299, 11, 'Easy straight-leg denim with a comfortable rise.'),
    ('Kids Color Block T-Shirt', 'kids-color-block-tshirt', 'Kidswear', '2Y, 4Y, 6Y, 8Y', 'Sunshine yellow', 499, 399, 32, 'Soft color-block tee made for play days.'),
    ("Men's Weekend Hoodie", 'mens-weekend-hoodie', 'Hoodies', 'M, L, XL', 'Charcoal', 1799, 1499, 9, 'Midweight fleece hoodie with a front pocket.'),
    ("Women's Daylight Dress", 'womens-daylight-dress', 'Dresses', 'S, M, L, XL', 'Lavender', 1899, 1499, 8, 'Easy-fit day dress in a soft woven fabric.'),
    ('Traditional Cotton Kurta', 'traditional-cotton-kurta', 'Kurtas', 'M, L, XL, XXL', 'Ivory', 1399, 1099, 14, 'Classic cotton kurta with a simple placket.'),
]

PALETTE = [
    ('#dcebf2', '#4380a1'), ('#e0ece4', '#367654'), ('#e4e8f0', '#384f83'),
    ('#f6ead1', '#c08b31'), ('#f2e1e4', '#a94f69'), ('#e3e6ef', '#455a8d'),
    ('#f4ebc9', '#c49e36'), ('#e2e2e2', '#555b63'), ('#eee4f2', '#8a659d'), ('#f0eadc', '#9c8458'),
]


def demo_image(label, size, background, accent, kind='product'):
    image = Image.new('RGB', size, background)
    draw = ImageDraw.Draw(image)
    width, height = size
    if kind == 'banner':
        draw.ellipse((width - 260, 20, width + 80, height + 320), fill='#ffffff')
        draw.rounded_rectangle((width - 245, 55, width - 95, height - 45), radius=45, fill=accent)
        draw.text((48, 65), 'ABC FASHION', fill='#176c53', font=ImageFont.load_default())
        draw.text((48, 130), label[:35], fill='#24372e', font=ImageFont.load_default())
    else:
        draw.ellipse((width * .12, height * .1, width * .88, height * .86), fill='#ffffff')
        draw.polygon(((width * .39, height * .25), (width * .29, height * .34), (width * .35, height * .54), (width * .42, height * .51), (width * .42, height * .78), (width * .62, height * .78), (width * .62, height * .51), (width * .69, height * .54), (width * .75, height * .34), (width * .65, height * .25), (width * .57, height * .33), (width * .47, height * .33)), fill=accent)
        draw.text((18, height - 38), label[:28], fill='#25382f', font=ImageFont.load_default())
    output = BytesIO()
    image.save(output, format='PNG')
    return ContentFile(output.getvalue())


class Command(BaseCommand):
    help = 'Create fictional local development data for Shop Coin.'

    def add_arguments(self, parser):
        parser.add_argument('--password', required=True, help='Temporary password assigned to demo accounts.')

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError('seed_demo_data is available only when DJANGO_DEBUG is enabled.')
        password = options['password']
        if len(password) < 12:
            raise CommandError('Use a demo password of at least 12 characters.')

        demo_usernames = [SHOPKEEPER_USERNAME, *(f'demo_customer_{number:02d}' for number in range(1, 11))]
        for username in demo_usernames:
            existing_user = User.objects.filter(username=username).first()
            if existing_user:
                existing_profile = getattr(existing_user, 'profile', None)
                if existing_profile is None or not existing_profile.is_demo:
                    raise CommandError(f'Username {username!r} already belongs to a non-demo account.')
        existing_shop = Shop.objects.filter(slug=SHOP_SLUG).first()
        if existing_shop and not existing_shop.is_demo:
            raise CommandError(f'Shop slug {SHOP_SLUG!r} is already used by a non-demo shop.')
        if existing_shop:
            for _, slug, *_ in PRODUCTS:
                existing_product = Product.objects.filter(shop=existing_shop, slug=slug).first()
                if existing_product and not existing_product.is_demo:
                    raise CommandError(f'Product slug {slug!r} is already used by a non-demo product.')
            existing_offer = ShopOffer.objects.filter(shop=existing_shop, title='Demo New Season Offer').first()
            if existing_offer and not existing_offer.is_demo:
                raise CommandError('The demo offer title is already used by a non-demo offer.')
            existing_ad = ShopAd.objects.filter(shop=existing_shop, title='Demo Winter Sale').first()
            if existing_ad and not existing_ad.is_demo:
                raise CommandError('The demo ad title is already used by a non-demo ad.')

        owner = self.demo_user(SHOPKEEPER_USERNAME, 'Demo', 'Shopkeeper', 'demo.shopkeeper@example.test', password, UserProfile.Role.SHOPKEEPER)
        ShopkeeperProfile.objects.update_or_create(user=owner, defaults={'phone': '0000000001', 'business_name': 'ABC Fashion Store', 'contact_email': owner.email})
        shop, created = Shop.objects.get_or_create(
            slug=SHOP_SLUG,
            defaults={
                'owner': owner, 'name': 'ABC Fashion Store', 'description': 'Fictional demonstration clothing shop for local development.',
                'phone': '0000000001', 'email': 'demo.shop@example.test', 'address': '100 Demo Market, Test Nagar',
                'city': 'Samplepur', 'state': 'Demostate', 'pincode': '000000', 'status': Shop.Status.APPROVED, 'is_demo': True,
            },
        )
        shop.owner = owner
        shop.name = 'ABC Fashion Store'
        shop.description = 'Fictional demonstration clothing shop for local development.'
        shop.phone = '0000000001'
        shop.email = 'demo.shop@example.test'
        shop.address = '100 Demo Market, Test Nagar'
        shop.city = 'Samplepur'
        shop.state = 'Demostate'
        shop.pincode = '000000'
        shop.status = Shop.Status.APPROVED
        shop.is_demo = True
        if not shop.logo:
            shop.logo.save('abc-fashion-demo-logo.png', demo_image('ABC', (400, 400), '#e5f2ea', '#43856a'), save=False)
        if not shop.banner:
            shop.banner.save('abc-fashion-demo-banner.png', demo_image('Local style, made simple', (1200, 420), '#deeee4', '#4d8c72', kind='banner'), save=False)
        shop.save()

        for index, item in enumerate(PRODUCTS):
            name, slug, category, sizes, color, price, discount, stock, description = item
            product, created = Product.objects.get_or_create(
                shop=shop, slug=slug,
                defaults={
                    'name': name, 'price': price, 'discount_price': discount, 'category': category,
                    'sizes': sizes, 'colors': color, 'description': description, 'stock': stock,
                    'is_active': True, 'is_new': index in (0, 1, 3, 6, 8), 'is_demo': True,
                },
            )
            if not created and not product.is_demo:
                raise CommandError(f'Product slug {slug!r} is already used by a non-demo product.')
            product.name = name
            product.price = price
            product.discount_price = discount
            product.category = category
            product.sizes = sizes
            product.colors = color
            product.description = description
            product.stock = stock
            product.is_active = True
            product.is_new = index in (0, 1, 3, 6, 8)
            product.is_demo = True
            if not product.image:
                background, accent = PALETTE[index]
                product.image.save(f'{slug}-demo.png', demo_image(name, (640, 720), background, accent), save=False)
            product.save()

        now = timezone.now()
        offer, created = ShopOffer.objects.get_or_create(
            shop=shop, title='Demo New Season Offer',
            defaults={'description': 'Fictional sample offer for development.', 'badge': 'UP TO 30% OFF', 'starts_at': now - timedelta(days=1), 'ends_at': now + timedelta(days=14), 'is_active': True, 'is_demo': True},
        )
        if not created and not offer.is_demo:
            raise CommandError('The demo offer title is already used by a non-demo offer.')
        offer.description = 'Fictional sample offer for development.'
        offer.badge = 'UP TO 30% OFF'
        offer.starts_at = now - timedelta(days=1)
        offer.ends_at = now + timedelta(days=14)
        offer.is_active = True
        offer.is_demo = True
        offer.save()

        today = date.today()
        ad, created = ShopAd.objects.get_or_create(
            shop=shop, title='Demo Winter Sale',
            defaults={'description': 'New winter collection available in this sample shop.', 'offer_text': 'Up to 30% OFF', 'start_date': today, 'end_date': today + timedelta(days=14), 'is_active': True, 'is_demo': True},
        )
        if not created and not ad.is_demo:
            raise CommandError('The demo ad title is already used by a non-demo ad.')
        ad.description = 'New winter collection available in this sample shop.'
        ad.offer_text = 'Up to 30% OFF'
        ad.start_date = today
        ad.end_date = today + timedelta(days=14)
        ad.is_active = True
        ad.is_demo = True
        if not ad.image:
            ad.image.save('demo-winter-sale.png', demo_image('Winter Sale · Up to 30% OFF', (1200, 500), '#e5f2ea', '#d6ae53', kind='banner'), save=False)
        ad.save()

        for number in range(1, 11):
            suffix = f'{number:02d}'
            username = f'demo_customer_{suffix}'
            user = self.demo_user(username, 'Demo', f'Customer {suffix}', f'demo.customer.{suffix}@example.test', password, UserProfile.Role.CUSTOMER)
            phone = f'00000001{number:02d}'
            profile, profile_created = CustomerProfile.objects.get_or_create(
                user=user, defaults={'phone': phone, 'connected_shop': shop},
            )
            if profile.connected_shop_id not in (None, shop.pk):
                raise CommandError(f'{username} is already connected to another shop.')
            profile.phone = phone
            profile.connected_shop = shop
            profile.save(update_fields=('phone', 'connected_shop', 'updated_at'))

        self.stdout.write(self.style.SUCCESS('Demo data ready: 1 approved shop, 10 products, 1 ad, 1 offer, and 10 connected customers.'))
        self.stdout.write('Demo usernames: demo_shopkeeper and demo_customer_01 through demo_customer_10.')

    def demo_user(self, username, first_name, last_name, email, password, role):
        user, created = User.objects.get_or_create(
            username=username,
            defaults={'first_name': first_name, 'last_name': last_name, 'email': email},
        )
        profile = getattr(user, 'profile', None)
        if profile and not profile.is_demo:
            raise CommandError(f'Username {username!r} belongs to a non-demo account.')
        user.first_name = first_name
        user.last_name = last_name
        user.email = email
        user.set_password(password)
        user.save()
        UserProfile.objects.update_or_create(user=user, defaults={'role': role, 'is_demo': True})
        return user
