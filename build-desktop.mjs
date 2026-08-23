import { createHash } from 'node:crypto'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const pluginRoot = dirname(fileURLToPath(import.meta.url))
const hermesHome = resolve(pluginRoot, '..', '..')
const sourceRoot = join(pluginRoot, 'desktop-src')
const outputRoot = join(pluginRoot, 'desktop')
const outputFile = join(outputRoot, 'plugin.js')

const agentRoots = [
  process.env.HERMES_AGENT_SOURCE,
  join(hermesHome, 'hermes-agent'),
  join(sourceRoot, 'node_modules'),   // P0-D：CI/开源环境（npm ci 后 esbuild 装在 desktop-src）
].filter(Boolean)

const agentRoot = agentRoots.find(root => existsSync(join(root, 'node_modules', 'esbuild', 'package.json')))
if (!agentRoot) {
  throw new Error('Cannot find Hermes Agent source with esbuild. Set HERMES_AGENT_SOURCE to the repository root.')
}

const requireFromHermes = createRequire(join(agentRoot, 'package.json'))
const { build } = requireFromHermes('esbuild')

const styleModule = {
  name: 'workbench-css-inline',
  setup(builder) {
    builder.onLoad({ filter: /workbench\.css$/ }, args => {
      const css = readFileSync(args.path, 'utf8')
      return {
        loader: 'js',
        contents: `
const id = 'hermes-plugin-style-workbench-view';
let node = document.getElementById(id);
if (!node) {
  node = document.createElement('style');
  node.id = id;
  document.head.appendChild(node);
}
node.textContent = ${JSON.stringify(css)};
`,
      }
    })
  },
}

mkdirSync(outputRoot, { recursive: true })
await build({
  entryPoints: [join(sourceRoot, 'plugin.tsx')],
  outfile: outputFile,
  bundle: true,
  format: 'esm',
  platform: 'browser',
  target: ['es2022'],
  jsx: 'automatic',
  external: ['@hermes/plugin-sdk', 'react', 'react/jsx-runtime'],
  plugins: [styleModule],
  legalComments: 'none',
  sourcemap: false,
  charset: 'utf8',
  logLevel: 'info',
})

const built = readFileSync(outputFile, 'utf8')
const imports = [...built.matchAll(/(?:from\s*|import\s*\(\s*|import\s+)["']([^"']+)["']/g)].map(match => match[1])
const allowed = new Set(['@hermes/plugin-sdk', 'react', 'react/jsx-runtime'])
const unsupported = [...new Set(imports.filter(specifier => !allowed.has(specifier)))]

if (unsupported.length > 0) {
  throw new Error(`Desktop bundle contains unsupported imports: ${unsupported.join(', ')}`)
}
if (!/export\s*\{[\s\S]*default/.test(built)) {
  throw new Error('Desktop bundle has no default export')
}

const sha256 = createHash('sha256').update(built).digest('hex')
const buildInfo = {
  plugin: 'workbench-view',
  delivery: 'unified-disk-plugin',
  generatedAt: new Date().toISOString(),
  hermesAgentSource: 'hermes-agent',   // P0-E：中性值，不落个人绝对路径
  esbuild: requireFromHermes('esbuild/package.json').version,
  output: 'desktop/plugin.js',
  sha256,
  externalImports: [...new Set(imports)].sort(),
}
writeFileSync(join(outputRoot, 'build-info.json'), `${JSON.stringify(buildInfo, null, 2)}\n`, 'utf8')
console.log(JSON.stringify(buildInfo, null, 2))
