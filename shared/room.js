/*
 * Shared gallery helper. Each room includes this file and calls Gallery.mount().
 * The helper gives three things:
 *   1. An entry overlay. The visitor clicks it, and the browser lets us start sound.
 *   2. A small navigation chip with links to the hub and to the previous and next room.
 *   3. A sound toggle that mutes or unmutes the master gain node.
 * The helper does not set any style for the room itself. Each room has its own style.
 */
(function () {
  const ROOT = document.currentScript.src.replace(/shared\/room\.js.*$/, '');
  const css = `
  .g-overlay{position:fixed;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;background:rgba(0,0,0,.72);color:#fff;z-index:9999;font-family:system-ui,sans-serif;text-align:center;padding:24px;cursor:pointer}
  .g-overlay h1{font-size:clamp(22px,4vw,40px);margin:0;font-weight:600}
  .g-overlay p{max-width:560px;margin:0;opacity:.85;line-height:1.5;font-size:15px}
  .g-overlay .g-btn{margin-top:14px;padding:12px 26px;border:1px solid #fff;border-radius:999px;font-size:15px;background:transparent;color:#fff;cursor:pointer}
  .g-nav{position:fixed;left:12px;bottom:12px;display:flex;gap:6px;z-index:9998;font-family:system-ui,sans-serif;font-size:12px}
  .g-nav a,.g-nav button{background:rgba(20,20,20,.75);color:#fff;border:1px solid rgba(255,255,255,.35);border-radius:999px;padding:6px 11px;text-decoration:none;cursor:pointer;backdrop-filter:blur(6px)}
  .g-nav a:hover,.g-nav button:hover{background:rgba(60,60,60,.9)}
  @media (max-width:600px){.g-nav{left:8px;bottom:8px;font-size:11px}}`;
  const style = document.createElement('style');
  style.textContent = css;
  document.head.appendChild(style);

  /*
   * Binary fallback. Some hosts do not serve raw binary files such as .bin or .i16.
   * When a fetch for a binary file fails, this wrapper loads a base64 text copy
   * with the same name plus ".b64.txt" and decodes it into bytes.
   */
  const BIN = /\.(bin|i16|i8|u8|u16|f32)$/i;
  const origFetch = window.fetch.bind(window);
  window.fetch = async function (url, opts) {
    const u = typeof url === 'string' ? url : (url && url.url) || '';
    if (!BIN.test(u.split('?')[0])) return origFetch(url, opts);
    let r = null;
    try { r = await origFetch(url, opts); } catch (e) { r = null; }
    if (r && r.ok) {
      const ct = (r.headers.get('content-type') || '').toLowerCase();
      if (!ct.startsWith('text/html')) return r;
    }
    const t = await origFetch(u + '.b64.txt', opts);
    if (!t.ok) return r || t;
    const b64 = (await t.text()).trim();
    const bin = atob(b64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return new Response(bytes, { status: 200, headers: { 'Content-Type': 'application/octet-stream' } });
  };

  const Gallery = {
    audio: null,
    master: null,
    muted: false,
    /*
     * opts.slug: the room slug, used to find the neighbors in rooms.json.
     * opts.title: the title on the entry overlay.
     * opts.blurb: one or two sentences on what the visitor sees and hears.
     * opts.onStart(audioContext, masterGain): called once when the visitor enters.
     */
    mount(opts) {
      const ov = document.createElement('div');
      ov.className = 'g-overlay';
      ov.innerHTML = `<h1>${opts.title}</h1><p>${opts.blurb || ''}</p><button class="g-btn">Enter with sound</button>`;
      document.body.appendChild(ov);
      const start = () => {
        ov.remove();
        try {
          const AC = window.AudioContext || window.webkitAudioContext;
          Gallery.audio = new AC();
          Gallery.master = Gallery.audio.createGain();
          Gallery.master.gain.value = 0.8;
          Gallery.master.connect(Gallery.audio.destination);
          Gallery.audio.resume();
        } catch (e) { Gallery.audio = null; }
        opts.onStart(Gallery.audio, Gallery.master);
      };
      ov.addEventListener('click', start, { once: true });
      this.nav(opts.slug);
    },
    nav(slug) {
      const nav = document.createElement('div');
      nav.className = 'g-nav';
      nav.innerHTML = `<a href="${ROOT}index.html" title="Gallery hub">Gallery</a><a data-prev href="#">Prev</a><a data-next href="#">Next</a><button data-mute>Sound: on</button>`;
      document.body.appendChild(nav);
      nav.querySelector('[data-mute]').addEventListener('click', (e) => {
        Gallery.muted = !Gallery.muted;
        if (Gallery.master) Gallery.master.gain.value = Gallery.muted ? 0 : 0.8;
        e.target.textContent = Gallery.muted ? 'Sound: off' : 'Sound: on';
      });
      fetch(ROOT + 'rooms.json').then(r => r.json()).then(rooms => {
        const i = rooms.findIndex(r => r.slug === slug);
        if (i < 0) return;
        const prev = rooms[(i - 1 + rooms.length) % rooms.length];
        const next = rooms[(i + 1) % rooms.length];
        nav.querySelector('[data-prev]').href = `${ROOT}rooms/${prev.slug}/index.html`;
        nav.querySelector('[data-prev]').title = prev.title;
        nav.querySelector('[data-next]').href = `${ROOT}rooms/${next.slug}/index.html`;
        nav.querySelector('[data-next]').title = next.title;
      }).catch(() => {});
    }
  };
  window.Gallery = Gallery;
})();
