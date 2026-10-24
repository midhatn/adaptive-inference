import {build} from 'esbuild';
import fs from 'node:fs';
import path from 'node:path';
import {createHash} from 'node:crypto';
const entries=[
  {repo:'continue',revision:'5522c6f44ca0ac3528b37244818fbfa39b5af470',entry:'packages/openai-adapters/src/apis/OpenAI.ts',output:'continue-current.mjs'},
  {repo:'continue',revision:'5522c6f44ca0ac3528b37244818fbfa39b5af470',entry:'packages/config-yaml/src/schemas/models.ts',output:'continue-schema.mjs'},
  {repo:'cline',revision:'c7db4bfbd2643425e3c185367cb8c8b4bc468c4f',entry:'sdk/packages/llms/src/providers/gateway.ts',output:'cline-current.mjs'},
];
const hash=(file)=>createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const manifest=JSON.parse(fs.readFileSync('../source-manifest.json','utf8'));
if(manifest.schema!=='adaptive-inference.client-source-closure.v1')throw Error('Invalid source manifest');
for(const repo of manifest.repositories){
  const root=path.resolve('../sources',repo.id);
  if(!repo.files.some(f=>f.kind==='license'))throw Error('Missing original license');
  for(const row of repo.files){
    const target=path.resolve(root,row.path);
    if(!target.startsWith(root+path.sep)||fs.statSync(target).size!==row.bytes||hash(target)!==row.sha256)throw Error('Source hash mismatch: '+repo.id+'/'+row.path);
  }
}
for(const entry of entries){
  const dir=path.resolve('../sources',entry.repo);
  const actual=manifest.repositories.find(repo=>repo.id===entry.repo)?.revision;
  if(actual!==entry.revision)throw Error('Unpinned source '+entry.repo);
  const alias=entry.repo==='continue'?{zod:path.resolve('node_modules/@continuedev/config-yaml/node_modules/zod/index.js')}:{};
  const built=await build({entryPoints:[path.join(dir,entry.entry)],outfile:entry.output,bundle:true,packages:'external',format:'esm',platform:'node',metafile:true,alias});
  entry.inputs=Object.keys(built.metafile.inputs).map(file=>{const relative=path.relative(dir,path.resolve(file)).replaceAll('\\','/');return relative.startsWith('../')?{dependency_path:path.relative(path.resolve('node_modules'),path.resolve(file)).replaceAll('\\','/'),sha256:hash(file)}:{path:relative,sha256:hash(file)};});
  entry.output_sha256=hash(entry.output);
}
fs.writeFileSync('source-pins.json',JSON.stringify({schema:'adaptive-inference.client-source-pins.v1',entries,dependency_lock_sha256:hash('bun.lock')},null,2)+'\n');
console.log('Built '+entries.length+' pinned source entry points; external dependencies remain lockfile-bound.');
