import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../dist/minime-frontend/browser');
const port = Number(process.env.PORT || 8788);
const contentTypes = {
  '.css': 'text/css', '.js': 'text/javascript', '.json': 'application/json',
  '.png': 'image/png', '.svg': 'image/svg+xml', '.ico': 'image/x-icon',
};

http.createServer((request, response) => {
  const requested = decodeURIComponent(new URL(request.url, `http://127.0.0.1:${port}`).pathname);
  const relative = requested === '/' ? 'index.html' : requested.replace(/^\//, '');
  const candidate = path.resolve(root, relative);
  const file = candidate.startsWith(`${root}${path.sep}`) && fs.existsSync(candidate) && fs.statSync(candidate).isFile()
    ? candidate
    : path.join(root, 'index.html');
  response.writeHead(200, { 'Content-Type': contentTypes[path.extname(file)] || 'text/html' });
  fs.createReadStream(file).pipe(response);
}).listen(port, '127.0.0.1');
