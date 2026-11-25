import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const candidateRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../dist/minime-frontend');
const root = fs.existsSync(path.join(candidateRoot, 'browser')) ? path.join(candidateRoot, 'browser') : candidateRoot;
const port = Number(process.env.PORT || 8788);
const contentTypes = {
  '.css': 'text/css', '.js': 'text/javascript', '.json': 'application/json',
  '.png': 'image/png', '.svg': 'image/svg+xml', '.ico': 'image/x-icon',
};

http.createServer((request, response) => {
  if (request.url === '/health/live') {
    response.writeHead(200, { 'Content-Type': 'application/json' });
    response.end(JSON.stringify({ status: 'healthy', database: { engine: 'PostgreSQL', healthy: true } }));
    return;
  }
  const requested = decodeURIComponent(new URL(request.url, `http://127.0.0.1:${port}`).pathname);
  const relative = requested === '/' ? 'index.html' : requested.replace(/^\//, '');
  const candidate = path.resolve(root, relative);
  const file = candidate.startsWith(`${root}${path.sep}`) && fs.existsSync(candidate) && fs.statSync(candidate).isFile()
    ? candidate
    : path.join(root, 'index.html');
  response.writeHead(200, { 'Content-Type': contentTypes[path.extname(file)] || 'text/html' });
  fs.createReadStream(file).pipe(response);
}).listen(port, '127.0.0.1');
