// Cloudflare Worker for photosnob.com. Every file is served straight from public/; this script only runs
// when no file matches. A few product addresses contain non-English characters (【 ，) that Cloudflare
// can't use as file names, so those pages are stored under an ASCII name (each such character -> "-").
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    let path;
    try { path = decodeURIComponent(url.pathname); } catch { path = url.pathname; }
    const ascii = path.replace(/[^\x00-\x7f]/g, '-');
    if (ascii !== path) {
      url.pathname = ascii;
      return env.ASSETS.fetch(new Request(url, request));
    }
    return env.ASSETS.fetch(request); // falls through to the 404 page
  },
};
