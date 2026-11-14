"""Static description images from explicit HTTPS asset origins, never websites."""
import re
import ssl
import urllib.request
from urllib.parse import urlsplit
import certifi
from nexus_launcher.secure_http import OriginRedirects, origin
from .mod_media import MediaCache, MAX_BYTES, fetch_checked_media

MAX_DESCRIPTION_IMAGES=24
PATHS={
    'cdn.modrinth.com':r'/.*',
    'raw.githubusercontent.com':r'/.*',
    'user-images.githubusercontent.com':r'/.*',
    'user-attachments.githubusercontent.com':r'/.*',
    'private-user-images.githubusercontent.com':r'/.*',
    'github.com':r'(?:/[^/]+/[^/]+/assets/.*|/user-attachments/assets/.*)',
    'github-production-user-asset-6210df.s3.amazonaws.com':r'/[0-9]+/[^/]+',
    'tr7zw.github.io':r'/uikit/banner/.*',
    'tr7zw.dev':r'/nea/.*',
}


def safe_description_image(url):
    try:
        if not isinstance(url,str) or len(url)>8192 or any(ord(c)<32 for c in url):return False
        _,host,_=origin(url)
        path=urlsplit(url).path
        return host in PATHS and re.fullmatch(PATHS[host],path) is not None
    except (ValueError,TypeError):return False


class DescriptionRedirects(OriginRedirects):
    def __init__(self):super().__init__({('https',host,443) for host in PATHS})
    def validate(self,url):
        if not safe_description_image(url):raise ValueError('Unapproved description image origin or path')


def open_description_image(request):
    policy=DescriptionRedirects();policy.validate(request.full_url)
    context=ssl.create_default_context();context.load_verify_locations(cafile=certifi.where())
    response=urllib.request.build_opener(policy,urllib.request.HTTPSHandler(context=context)).open(request,timeout=6)
    try:policy.validate(response.geturl())
    except Exception:
        response.close();raise
    return response


CACHE=MediaCache(validator=safe_description_image)


def fetch_description_media(url,cancelled=lambda:False,max_bytes=MAX_BYTES):
    return fetch_checked_media(url,cancelled,max_bytes,validator=safe_description_image,cache=CACHE,opener=open_description_image)
