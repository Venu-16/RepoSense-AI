import assert from 'node:assert/strict'
import { createServer as createHttpServer } from 'node:http'
import { after, test } from 'node:test'
import { createServer as createViteServer } from 'vite'
import viteConfig from '../vite.config.js'

let backend
let vite

after(async () => {
  if (vite) {
    await vite.close()
  }
  if (backend?.listening) {
    await new Promise((resolve, reject) => {
      backend.close((error) => error ? reject(error) : resolve())
    })
  }
})

test('Vite proxies API requests to the backend', async () => {
  assert.equal(viteConfig.server.proxy['/api'], 'http://127.0.0.1:8000')

  backend = createHttpServer((request, response) => {
    assert.equal(request.method, 'POST')
    assert.equal(request.url, '/api/ingest-repo')
    response.writeHead(200, { 'Content-Type': 'application/json' })
    response.end(JSON.stringify({ repo_name: 'owner/repo' }))
  })
  await new Promise((resolve, reject) => {
    backend.once('error', reject)
    backend.listen(0, '127.0.0.1', resolve)
  })

  const backendAddress = backend.address()
  vite = await createViteServer({
    ...viteConfig,
    configFile: false,
    server: {
      ...viteConfig.server,
      host: '127.0.0.1',
      port: 0,
      proxy: {
        '/api': `http://127.0.0.1:${backendAddress.port}`
      }
    }
  })
  await vite.listen()

  const viteAddress = vite.httpServer.address()
  const response = await fetch(`http://127.0.0.1:${viteAddress.port}/api/ingest-repo`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ repo_url: 'https://github.com/owner/repo' })
  })

  assert.equal(response.status, 200)
  assert.deepEqual(await response.json(), { repo_name: 'owner/repo' })
})
