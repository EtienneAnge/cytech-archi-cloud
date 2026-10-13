const express = require('express');
const path = require('path');

const app = express();
const PORT = process.env.PORT || 3000;

app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

const BASES = { bin: 2, dec: 10, hex: 16 };
const PATTERNS = { bin: /^[01]+$/, dec: /^[0-9]+$/, hex: /^[0-9a-f]+$/i };
const PREFIXES = { bin: '0b', hex: '0x' };

// POST /api/convert { value, from: "bin"|"dec"|"hex", to: "bin"|"dec"|"hex" }
app.post('/api/convert', (req, res) => {
  const { from, to } = req.body || {};
  let value = String(req.body?.value ?? '').trim().replace(/[\s_]/g, '');

  if (!(from in BASES) || !(to in BASES)) {
    return res.status(400).json({ error: 'from/to must be one of: bin, dec, hex' });
  }
  if (PREFIXES[from] && value.toLowerCase().startsWith(PREFIXES[from])) {
    value = value.slice(2);
  }
  if (!PATTERNS[from].test(value)) {
    return res.status(400).json({ error: `"${req.body.value}" is not a valid ${from} number` });
  }

  // BigInt keeps arbitrarily large numbers exact
  const prefix = { 2: '0b', 10: '', 16: '0x' }[BASES[from]];
  const n = BigInt(prefix + value);
  let result = n.toString(BASES[to]);
  if (to === 'hex') result = result.toUpperCase();

  res.json({ input: value, from, to, result });
});

app.get('/live', (req, res) => res.sendStatus(200));
app.get('/ready', (req, res) => res.sendStatus(200));


app.listen(PORT, () => console.log(`Converter running on http://localhost:${PORT}`));


