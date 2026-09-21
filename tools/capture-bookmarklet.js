// Crown AI — one-click amendment capture.
//
// Runs on the amendment page itself, so it reads the page's own bytes rather
// than asking you to view source and paste them. Everything happens in your
// browser: it makes no network requests, sends nothing anywhere, and the only
// thing that leaves is a file you save yourself.
//
// tools/bookmarklet.html turns this into a draggable bookmark. You can also
// paste it straight into the browser console on the amendment page.
(function () {
  if (document.getElementById('crown-capture-panel')) return;

  // --- sha256, so the bundle can be fingerprinted with no secure-context
  //     requirement and no dependency. Matches Python's hashlib.sha256.
  function sha256(str) {
    function rr(n, x) { return (n >>> x) | (n << (32 - x)); }
    var K = [], H = [], primes = [], n = 2, i;
    while (primes.length < 64) {
      var isPrime = true;
      for (var f = 2; f * f <= n; f++) if (n % f === 0) { isPrime = false; break; }
      if (isPrime) primes.push(n);
      n++;
    }
    for (i = 0; i < 64; i++) K[i] = (Math.pow(primes[i], 1 / 3) % 1 * 0x100000000) | 0;
    for (i = 0; i < 8; i++) H[i] = (Math.pow(primes[i], 1 / 2) % 1 * 0x100000000) | 0;
    var bytes = new TextEncoder().encode(str), bitLen = bytes.length * 8;
    var m = [], j;
    for (j = 0; j < bytes.length; j++) m.push(bytes[j]);
    m.push(0x80);
    while (m.length % 64 !== 56) m.push(0);
    var dv = new DataView(new ArrayBuffer(8));
    dv.setBigUint64(0, BigInt(bitLen));
    for (j = 0; j < 8; j++) m.push(dv.getUint8(j));
    var w = new Int32Array(64);
    for (var off = 0; off < m.length; off += 64) {
      for (i = 0; i < 16; i++)
        w[i] = (m[off + i * 4] << 24) | (m[off + i * 4 + 1] << 16)
             | (m[off + i * 4 + 2] << 8) | m[off + i * 4 + 3];
      for (i = 16; i < 64; i++) {
        var s0 = rr(w[i - 15], 7) ^ rr(w[i - 15], 18) ^ (w[i - 15] >>> 3);
        var s1 = rr(w[i - 2], 17) ^ rr(w[i - 2], 19) ^ (w[i - 2] >>> 10);
        w[i] = (w[i - 16] + s0 + w[i - 7] + s1) | 0;
      }
      var a = H[0], b = H[1], c = H[2], d = H[3], e = H[4], f2 = H[5], g = H[6], h = H[7];
      for (i = 0; i < 64; i++) {
        var S1 = rr(e, 6) ^ rr(e, 11) ^ rr(e, 25);
        var ch = (e & f2) ^ (~e & g);
        var t1 = (h + S1 + ch + K[i] + w[i]) | 0;
        var S0 = rr(a, 2) ^ rr(a, 13) ^ rr(a, 22);
        var maj = (a & b) ^ (a & c) ^ (b & c);
        var t2 = (S0 + maj) | 0;
        h = g; g = f2; f2 = e; e = (d + t1) | 0;
        d = c; c = b; b = a; a = (t1 + t2) | 0;
      }
      var v = [a, b, c, d, e, f2, g, h];
      for (i = 0; i < 8; i++) H[i] = (H[i] + v[i]) | 0;
    }
    return H.map(function (x) { return (x >>> 0).toString(16).padStart(8, '0'); }).join('');
  }

  // --- best-effort reading of the page. These are suggestions, and the panel
  //     will not export until you have confirmed them.
  var html = document.documentElement.outerHTML;
  var url = location.href;
  var text = document.body ? (document.body.innerText || '') : '';
  var STATUSES = ['GAZETTED', 'APPROVED', 'EXHIBITED', 'ADOPTED', 'ABANDONED', 'LAPSED'];
  var MONTHS = { January: '01', February: '02', March: '03', April: '04', May: '05',
                 June: '06', July: '07', August: '08', September: '09', October: '10',
                 November: '11', December: '12' };

  function guess() {
    var number = (url.match(/\/amendments\/([A-Za-z0-9]+)/) || [])[1]
              || (text.match(/\b([Cc]\d{2,4}[a-z]{0,6})\b/) || [])[1] || '';
    var lga = (url.match(/\/([A-Za-z%20 ]+)\/amendments\//) || [])[1] || '';
    var status = '';
    for (var i = 0; i < STATUSES.length; i++)
      if (new RegExp(STATUSES[i], 'i').test(text)) { status = STATUSES[i]; break; }
    var observed = (text.match(/\b(\d{4}-\d{2}-\d{2})\b/) || [])[1] || '';
    if (!observed) {
      var dmy = text.match(/\b(\d{1,2})\s+([A-Z][a-z]+)\s+(\d{4})\b/);
      if (dmy && MONTHS[dmy[2]])
        observed = dmy[3] + '-' + MONTHS[dmy[2]] + '-' + ('0' + dmy[1]).slice(-2);
    }
    var h1 = document.querySelector('h1');
    return {
      amendment_number: decodeURIComponent(number),
      lga: decodeURIComponent(lga),
      title: ((h1 && h1.textContent) || document.title || '').trim().slice(0, 200),
      status: status,
      observed_at: observed,
      suburb: ''
    };
  }

  // --- the panel
  var FIELDS = [
    ['amendment_number', 'Amendment number'],
    ['lga', 'LGA'],
    ['title', 'Title'],
    ['status', 'Status (GAZETTED / EXHIBITED / ...)'],
    ['observed_at', 'Date true upstream (YYYY-MM-DD)'],
    ['suburb', 'Suburb / precinct (optional)']
  ];
  var g = guess();
  var hash = sha256(html);

  var panel = document.createElement('div');
  panel.id = 'crown-capture-panel';
  panel.style.cssText = 'position:fixed;top:12px;right:12px;width:430px;z-index:2147483647;' +
    'background:#fff;color:#1a1a1a;border:2px solid #14213d;border-radius:6px;' +
    'font:13px/1.5 system-ui,sans-serif;box-shadow:0 8px 28px rgba(0,0,0,.3);' +
    'max-height:92vh;overflow:auto';
  var rows = FIELDS.map(function (f) {
    return '<div style="margin:6px 0"><label style="display:block;font-size:11px;color:#555">' +
      f[1] + '</label><input data-k="' + f[0] + '" value="' +
      String(g[f[0]] || '').replace(/"/g, '&quot;') +
      '" style="width:100%;box-sizing:border-box;padding:4px 6px;font:13px system-ui;' +
      'border:1px solid #bbb;border-radius:3px' + (g[f[0]] ? ';background:#fffbe8' : '') +
      '"></div>';
  }).join('');

  panel.innerHTML =
    '<div style="background:#14213d;color:#fff;padding:8px 12px;font-weight:600">' +
      'Crown AI — capture' +
      '<span id="crown-x" style="float:right;cursor:pointer">&times;</span></div>' +
    '<div style="padding:10px 12px">' +
      '<div style="background:#fff6e0;border:1px solid #c99700;padding:7px 9px;' +
        'font-size:12px;margin-bottom:8px">Highlighted fields were read off this page and ' +
        '<b>may be wrong</b>. Check each against what you can see. Blank fields go to the ' +
        'review queue, not the graph.</div>' +
      rows +
      '<div style="font-size:11px;color:#555;margin:8px 0">' +
        html.length.toLocaleString() + ' characters · sha256 ' + hash.slice(0, 16) + '…</div>' +
      '<label style="display:block;margin:8px 0;font-size:12px">' +
        '<input type="checkbox" id="crown-ok"> I have checked every field above against this page.' +
      '</label>' +
      '<button id="crown-save" style="font:13px system-ui;padding:6px 12px;cursor:pointer">' +
        'Save bundle</button>' +
      '<div id="crown-msg" style="font-size:12px;margin-top:8px"></div>' +
    '</div>';
  document.body.appendChild(panel);

  panel.querySelector('#crown-x').onclick = function () { panel.remove(); };
  Array.prototype.forEach.call(panel.querySelectorAll('input[data-k]'), function (i) {
    i.addEventListener('input', function () { i.style.background = '#fff'; });
  });

  panel.querySelector('#crown-save').onclick = function () {
    var msg = panel.querySelector('#crown-msg');
    if (!panel.querySelector('#crown-ok').checked) {
      msg.innerHTML = '<span style="color:#b00020">The importer refuses a bundle you have ' +
        'not confirmed.</span>';
      return;
    }
    var rec = {};
    Array.prototype.forEach.call(panel.querySelectorAll('input[data-k]'), function (i) {
      if (i.value.trim()) rec[i.dataset.k] = i.value.trim();
    });
    if (rec.suburb) { rec.geography = { suburbs: [rec.suburb] }; delete rec.suburb; }
    rec.detail_url = url;

    var bundle = {
      capture: {
        source_url: url,
        captured_at: new Date().toISOString(),
        page_title: document.title || null,
        sha256: hash,
        raw_html: html
      },
      confirmed_by_operator: true,
      records: [rec]
    };
    var name = 'crown-capture-' + (rec.amendment_number || hash.slice(0, 8)) + '.json';
    var a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([JSON.stringify(bundle, null, 2)],
                                          { type: 'application/json' }));
    a.download = name;
    a.click();
    msg.innerHTML = '<span style="color:#1a7f37">Saved ' + name + '</span>';
  };
})();
