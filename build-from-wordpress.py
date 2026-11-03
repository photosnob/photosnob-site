"""Turn the mirrored WordPress/WooCommerce site (photosnob.com) into a static site for Cloudflare Workers (static assets)."""
import os, re, glob, shutil, json, urllib.parse
from bs4 import BeautifulSoup, Comment
SRC = '/home/claude/src-photosnob/site'
OUT = '/home/claude/photosnob-site/public'
DOMAIN = 'photosnob.com'
# Shop pages that only work with a live WooCommerce store, plus WordPress's default sample page: dropped, redirected home.
DROP = {'cart', 'checkout', 'my-account', 'sample-page'}

def ascii_path(p):
    """Same rule as worker/index.js: decode %-escapes, then replace each non-ASCII character with '-'."""
    return re.sub(r'[^\x00-\x7f]', '-', urllib.parse.unquote(p))

def rel(s):
    """Make same-site URLs root-relative (works on workers.dev previews and the real domain)."""
    s = re.sub(r'https?:\\/\\/(?:www\.)?photosnob\.com(?![\w.-])', '', s)  # JSON-escaped, inside inline scripts
    return re.sub(r'(?:https?:)?//(?:www\.)?photosnob\.com(?![\w.-])', '', s)

# Scripts that need a live WordPress/WooCommerce backend (cart, account, AJAX, store analytics) or that drew the price popups
DROP_SCRIPT_IDS = re.compile(r'^(wc-add-to-cart|wc-cart-fragments|wc-jquery-blockui|wc-js-cookie|woocommerce|wc-order-attribution|sourcebuster|'
                             r'woocommerce-analytics|jetpack-stats|thickbox|WooZone-frontend-script|wp-emoji-settings|jetpack_related-posts)(-js)*(-extra|-before|-after)?$')
DROP_SCRIPT_BODY = ('window._wca', 'wcAnalytics', 'script#wp-emoji-settings', '_stq')

def strip_offers(node):
    """Remove price offers from Product structured data (prices are no longer shown)."""
    if isinstance(node, dict):
        if node.get('@type') == 'Product': node.pop('offers', None)
        for v in node.values(): strip_offers(v)
    elif isinstance(node, list):
        for v in node: strip_offers(v)

def clean(path, t, shell_page=False):
    s = BeautifulSoup(t, 'lxml')
    # WordPress API / feed / pingback links have nothing to serve on a static site
    for l in s.select('link'):
        r = ' '.join(l.get('rel', []))
        if r in ('EditURI', 'wlwmanifest', 'https://api.w.org/', 'pingback', 'shortlink') or (
                r == 'alternate' and l.get('type') in ('application/json', 'application/rss+xml', 'application/json+oembed', 'text/xml+oembed')):
            l.decompose()
        elif 'thickbox' in (l.get('href') or '') or 'related-posts' in (l.get('href') or ''):
            l.decompose()
    for sc in s.find_all('script'):
        if sc.decomposed: continue
        body = sc.string or ''
        src = sc.get('src', '')
        bundle = SRC + src.split('?')[0] if src.startswith('/wp-content/cache/minify/') or '/photosnob.com/wp-content/cache/minify/' in src else None
        if bundle and '/photosnob.com/' in bundle: bundle = SRC + '/wp-content/cache/minify/' + bundle.rsplit('/', 1)[1]
        is_woozone = bundle is not None and os.path.exists(bundle) and open(bundle, errors='replace').read(40).startswith('WooZone=')
        if DROP_SCRIPT_IDS.match(sc.get('id', '')) or any(b in body for b in DROP_SCRIPT_BODY) or is_woozone:
            sc.decompose()
    # Prices (shown on product pages and in every product grid) and the WooZone price popups / country check
    for e in s.select('.price, #WooZone-price-disclaimer, .WooZone-country-check, .WooZone-product-data, [id^="WooZone-"]'):
        if not e.decomposed: e.decompose()
    # Header login / cart
    for e in s.select('.top-cart-wrapper, .top-account-wrapper, .widget_shopping_cart'):
        if not e.decomposed: e.decompose()
    for a in s.select('a[href]'):
        p = rel(a['href']).strip('/').split('?')[0].split('#')[0]
        if p in DROP and not a.decomposed:
            li = a.find_parent('li'); (li or a).decompose()
    # "Buy product" buttons go straight to Amazon; without this the theme would try to add them to a WooCommerce cart
    for a in s.select('a.ajax_add_to_cart'):
        a['class'] = [c for c in a.get('class', []) if c not in ('ajax_add_to_cart', 'add_to_cart_button')]
        a['target'] = '_blank'; a['rel'] = 'nofollow sponsored noopener'
    for f in s.select('form.cart[action*="amazon."]'):
        f['target'] = '_blank'
    # Show the product photo even before (or without) the gallery script, which normally fades it in
    if s.select_one('.woocommerce-product-gallery') is not None:
        st = s.new_tag('style'); st.string = '.woocommerce-product-gallery{opacity:1!important}'; s.head.append(st)
    # Jetpack "Related" posts load over WordPress AJAX, which no longer exists
    for e in s.select('#jp-relatedposts'):
        if not e.decomposed: e.decompose()
    # WooCommerce / WordPress files that came from the WordPress.com CDN are served from this site instead
    for tag in s.select('[src*="c0.wp.com/"], [href*="c0.wp.com/"]'):
        for k in ('src', 'href'):
            if tag.get(k) and 'c0.wp.com/' in tag[k]: tag[k] = re.sub(r'^(?:https?:)?//c0\.wp\.com/', '/wp-cdn/', tag[k])
    # Reviews can't be submitted to a static site
    for e in s.select('#review_form_wrapper, #respond, .comment-respond'):
        if not e.decomposed: e.decompose()
    # Search boxes go to the static search page
    for f in s.select('form[role=search], form.woocommerce-product-search, form.search-form'):
        f['action'] = '/search/'
        for i in f.select('input[name=post_type]'): i.decompose()
    # Mark the product / post / page body for the search index
    if not shell_page and path != 'index':
        body = s.select_one('div.product.type-product') or s.select_one('article .entry-content') or s.select_one('.entry-content')
        if body is not None and not path.startswith(('product-category/', 'category/', 'page/')) and '/page/' not in path:
            body['data-pagefind-body'] = ''
    # rewrite same-site URLs, but keep canonical/og/ld+json absolute for SEO
    for tag in s.find_all(True):
        for k, v in list(tag.attrs.items()):
            if isinstance(v, list): continue
            if tag.name == 'link' and k == 'href' and 'canonical' in tag.get('rel', []): continue
            if tag.name == 'meta' and k == 'content': continue
            if isinstance(v, str) and DOMAIN in v: tag[k] = rel(v)
    for c in s.find_all(string=lambda x: isinstance(x, Comment)):
        if DOMAIN in c: c.replace_with(Comment(rel(str(c))))
    for sc in s.find_all(['script', 'style']):
        if sc.get('type') == 'application/ld+json':
            try:
                data = json.loads(sc.string or '')
                strip_offers(data); sc.string = json.dumps(data, ensure_ascii=False)
            except ValueError:
                pass
            continue
        if sc.string and DOMAIN in sc.string: sc.string = rel(sc.string)
    return s

def page_files():
    for f in glob.glob(SRC + '/**/index.html', recursive=True):
        p = os.path.relpath(os.path.dirname(f), SRC)
        p = 'index' if p == '.' else p
        if p.startswith(('wp-content', 'wp-includes')): continue
        yield p, f

if os.path.exists(OUT): shutil.rmtree(OUT)
os.makedirs(OUT)
# assets keep their WordPress paths, so relative url()s inside the theme/plugin CSS keep working
for d in ('wp-content', 'wp-includes'):
    if os.path.isdir(f'{SRC}/{d}'):
        shutil.copytree(f'{SRC}/{d}', f'{OUT}/{d}', ignore=lambda dirpath, names: [n for n in names if os.path.isfile(os.path.join(dirpath, n)) and os.path.getsize(os.path.join(dirpath, n)) == 0])
if os.path.isdir(SRC + '/../c0'):
    shutil.copytree(SRC + '/../c0', OUT + '/wp-cdn')
for extra in ('ads.txt',):
    if os.path.getsize(f'{SRC}/{extra}') and not open(f'{SRC}/{extra}', errors='replace').read(200).lstrip().startswith('<'):
        shutil.copy(f'{SRC}/{extra}', f'{OUT}/{extra}')
kept = []
for p, f in sorted(page_files()):
    if p in DROP or p.split('/')[0] in DROP: continue
    t = open(f, encoding='utf-8', errors='replace').read()
    # A few product addresses contain non-English characters (【 ，); Cloudflare can't serve files under those names,
    # so they're stored under an ASCII name and worker/index.js maps the real address onto it
    dst = OUT + '/index.html' if p == 'index' else f'{OUT}/{ascii_path(p)}/index.html'
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    open(dst, 'w').write(str(clean(p, t)))
    kept.append('/' if p == 'index' else f'/{p}/')

def shell(title, inner, noindex=True):
    """A copy of the Affiliate Disclosure page with its body swapped out (keeps header, menu, sidebar, footer)."""
    s = clean('shell', open(SRC + '/affiliate-disclosure/index.html').read(), shell_page=True)
    c = s.select_one('.entry-content'); c.clear()
    c.append(BeautifulSoup(inner, 'html.parser'))
    h = s.select_one('h1.entry-title, h1.page-title, h1')
    if h is not None: h.string = title
    s.title.string = f'{title} – Photosnob.com'
    for l in s.select('link[rel=canonical], meta[property="og:url"], meta[property="og:title"], meta[name=description], meta[property="og:description"], script[type="application/ld+json"]'): l.decompose()
    for li in s.select('.current-menu-item, .current_page_item'):
        li['class'] = [c for c in li.get('class', []) if c not in ('current-menu-item', 'current_page_item')]
    if noindex: s.head.append(s.new_tag('meta', attrs={'name': 'robots', 'content': 'noindex'}))
    return s

open(OUT + '/404.html', 'w').write(str(shell('Page not found',
    '<p>The page you were looking for has moved or no longer exists.</p><p><a href="/">Back to the shop</a> &middot; <a href="/search/">Search the site</a></p>')))

SEARCH = '''<link href="/pagefind/pagefind-ui.css" rel="stylesheet">
<div id="search"></div>
<script src="/pagefind/pagefind-ui.js"></script>
<script>
  (function () {
    var ui = new PagefindUI({ element: '#search', showSubResults: false, showImages: true, resetStyles: false });
    var q = new URLSearchParams(location.search).get('s');
    if (q) ui.triggerSearch(q);
    document.querySelectorAll('form[role=search] input[name=s], form.woocommerce-product-search input[name=s]').forEach(function (i) { if (q) i.value = q; });
  })();
</script>
<style>#search{--pagefind-ui-font:inherit;margin-bottom:40px}#search .pagefind-ui__result-thumb{width:90px}</style>'''
os.makedirs(OUT + '/search', exist_ok=True)
open(OUT + '/search/index.html', 'w').write(str(shell('Search', SEARCH)))

# sitemap and robots
skip = re.compile(r'(^|/)page/\d+/$')
urls = sorted(u for u in kept if not skip.search(u))
open(OUT + '/sitemap.xml', 'w').write('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' +
    ''.join(f'  <url><loc>https://{DOMAIN}{u}</loc></url>\n' for u in urls) + '</urlset>\n')
open(OUT + '/robots.txt', 'w').write(f'User-agent: *\nAllow: /\n\nSitemap: https://{DOMAIN}/sitemap.xml\n')
red = ['# WooCommerce cart/account pages and the WordPress sample page (removed)']
red += [f'/{p}/   /   301' for p in sorted(DROP)]
red += ['/my-account/*   /   301', '/wishlist/   /   301', '/shop/   /   301',
        '', '# WordPress endpoints and feeds', '/feed/   /   301', '/comments/feed/   /   301', '/wp-login.php   /   301', '/wp-admin/   /   301',
        '/xmlrpc.php   /   301', '/wp-sitemap.xml   /sitemap.xml   301', '/sitemap_index.xml   /sitemap.xml   301', '/sitemap.html   /sitemap.xml   301',
        '', '# Old sitemap pieces from the WordPress sitemap plugin']
red += [f'/{x}   /sitemap.xml   301' for x in ('category-sitemap.xml', 'page-sitemap.xml', 'post-sitemap.xml', 'product-sitemap.xml', 'productcat-sitemap.xml', 'sitemap-misc.xml')]
open(OUT + '/_redirects', 'w').write('\n'.join(red) + '\n')
print('pages', len(kept), 'sitemap', len(urls))
