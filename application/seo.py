from django.contrib.sitemaps import Sitemap
from django.http import HttpResponse
from django.urls import reverse


class PublicSitemap(Sitemap):
    protocol = 'https'

    def items(self):
        return ['home', 'about', 'privacy']

    def location(self, item):
        return reverse(item)


def robots_txt(request):
    sitemap_url = request.build_absolute_uri(reverse('sitemap'))
    content = '\n'.join([
        'User-agent: *',
        'Allow: /',
        'Disallow: /accounts/',
        'Disallow: /admin/',
        'Disallow: /applications/',
        'Disallow: /dashboard/',
        'Disallow: /documents/',
        'Disallow: /interviews/',
        'Disallow: /reminders/',
        'Disallow: /add/',
        'Disallow: /edit/',
        'Disallow: /delete/',
        f'Sitemap: {sitemap_url}',
        '',
    ])
    return HttpResponse(content, content_type='text/plain; charset=utf-8')
