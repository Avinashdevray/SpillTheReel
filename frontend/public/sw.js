const BACKEND_URL = self.location.origin === 'http://localhost:8081'
  ? 'http://localhost:8000'
  : 'https://trans-dash-waves-cameras.trycloudflare.com';

const TOKEN_CACHE = 'spillthereel-auth';
const TOKEN_URL = '/_auth/token';
const shareTargetPath = '/share-target';

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', () => self.clients.claim());

async function readToken() {
  const cache = await caches.open(TOKEN_CACHE);
  const res = await cache.match(TOKEN_URL);
  return res ? res.text() : null;
}

async function writeToken(token) {
  const cache = await caches.open(TOKEN_CACHE);
  await cache.put(TOKEN_URL, new Response(token));
}

async function deleteToken() {
  const cache = await caches.open(TOKEN_CACHE);
  await cache.delete(TOKEN_URL);
}

self.addEventListener('message', async (event) => {
  if (event.data && event.data.type === 'AUTH_TOKEN') {
    await writeToken(event.data.token);
  }
  if (event.data && event.data.type === 'AUTH_LOGOUT') {
    await deleteToken();
  }
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  if (url.pathname === shareTargetPath && url.searchParams.has('text')) {
    event.respondWith(handleShareTarget(event.request, url));
    return;
  }

  event.respondWith(fetch(event.request));
});

function toastHtml(text) {
  return `<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>SpillTheReel</title></head>
<body style="margin:0;background:transparent">
<div id="t" style="position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:#1a1a2e;color:#e0e0e0;padding:10px 20px;border-radius:12px;font-family:-apple-system,sans-serif;font-size:14px;box-shadow:0 4px 24px rgba(0,0,0,.5);opacity:0;transition:opacity .3s">${text}</div>
<script>
requestAnimationFrame(()=>document.getElementById('t').style.opacity='1');
setTimeout(()=>{document.getElementById('t').style.opacity='0';setTimeout(()=>window.close(),350)},1800);
</script>
</body></html>`;
}

async function handleShareTarget(request, url) {
  const text = url.searchParams.get('text') || '';
  const sharedUrl = url.searchParams.get('url') || '';
  const candidate = sharedUrl + ' ' + text;
  const match = candidate.match(/https?:\/\/(?:www\.)?instagram\.com\/(?:reel|reels|p)\/[A-Za-z0-9_-]+/);
  const reelUrl = match ? match[0] : null;

  const token = await readToken();
  if (!token || !reelUrl) {
    return fetch(request);
  }

  try {
    const res = await fetch(`${BACKEND_URL}/ingest`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
      body: JSON.stringify({ url: reelUrl }),
    });

    if (res.ok) {
      return new Response(toastHtml('Reel saved \u2713'), {
        headers: { 'Content-Type': 'text/html;charset=utf-8' },
      });
    }
  } catch {}

  return fetch(request);
}
