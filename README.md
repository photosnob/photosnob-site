# photosnob.com

Photosnob.com, an Amazon-affiliate product shop, moved off WordPress/WooCommerce (WPX hosting) to a static site on Cloudflare Workers. Every push to `main` deploys.

The pages in `public/` are the live site's own HTML, styles and scripts, at their WordPress addresses. Product images load from Amazon, as before. Changes made in the move:

- **Prices removed** everywhere (product pages, product grids, and the price data in each product's structured data). They were saved copies of Amazon prices and went stale.
- "Buy product" buttons and links go straight to Amazon with the affiliate tag `interiorde06b-20`, in a new tab.
- Login/register, the cart, checkout and my-account were removed; those addresses redirect to the shop (`public/_redirects`).
- The search boxes go to `/search/`, a static search ([Pagefind](https://pagefind.app)) over every product and post, built on each deploy.
- WooCommerce and WordPress files that came from the WordPress.com CDN (c0.wp.com) are served from `public/wp-cdn/`.
- Jetpack related posts, Jetpack and WooCommerce stats, and the WooZone price popups were removed (they needed WordPress running). Google Analytics (G-0TM56Z4HTV) stays.
- `public/sitemap.xml` and `public/robots.txt` replace the WordPress sitemap plugin's.

## Editing

Each page is `public/<url>/index.html`: products under `public/product/`, categories under `public/product-category/`, blog posts at the top level. Edit the HTML directly, or ask Claude to. Cloudflare Workers serves files up to 25 MiB each and up to 20,000 files per site.

## Commands

```
npm install
npm run preview   # build the search index and serve locally
npm run deploy    # build and deploy by hand (normally Cloudflare does this on push)
```

Cloudflare build settings: build command `npm run build`, deploy command `npx wrangler deploy`.

`build-from-wordpress.py` is the one-time script that turned the WordPress copy into `public/`; it's kept for reference.
