import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import {createHash} from 'node:crypto';
import {constructLlmApi} from '@continuedev/openai-adapters';
import {createGateway} from '@cline/llms';
import YAML from 'yaml';

const current=process.argv.includes('--current-source');
const currentContinue=current?await import('./continue-current.mjs'):null;
const currentCline=current?await import('./cline-current.mjs'):null;
const makeApi=current?(config)=>new currentContinue.OpenAIApi(config):constructLlmApi;
const makeGateway=current?currentCline.createGateway:createGateway;
const currentSchema=current?await import('./continue-schema.mjs'):null;

const MODEL='qwen3.8-flash-next-iq3_s-adaptive-media-beta';
const TOOL={name:'read_status',description:'Read fixture status',parameters:{type:'object',properties:{name:{type:'string'}},required:['name']}};
const requests=[];
const server=http.createServer(async (req,res)=>{
  let text=''; for await (const chunk of req) text+=chunk;
  const body=JSON.parse(text||'{}');
  requests.push({path:req.url,authorization:req.headers.authorization,body});
  const common={id:'fixture',model:MODEL,created:0};
  if(body.stream){
    res.writeHead(200,{'content-type':'text/event-stream'});
    for(const [delta,finish] of [[{role:'assistant',content:'fixture response'},null],[{},'stop']])
      res.write('data: '+JSON.stringify({...common,object:'chat.completion.chunk',choices:[{index:0,delta,finish_reason:finish}]})+'\n\n');
    res.end('data: [DONE]\n\n');
  }else{
    res.writeHead(200,{'content-type':'application/json'});
    res.end(JSON.stringify({...common,object:'chat.completion',choices:[{index:0,message:{role:'assistant',content:'fixture response'},finish_reason:'stop'}],usage:{prompt_tokens:1,completion_tokens:1,total_tokens:2}}));
  }
});
await new Promise(r=>server.listen(0,'127.0.0.1',r));
const base=`http://127.0.0.1:${server.address().port}`;
const checks=[];
try{
  for(const route of ['/v1','/background/v1']){
    const model=YAML.parse(`name: Fixture route\nprovider: openai\nmodel: ${MODEL}\napiBase: ${base+route}\napiKey: fixture-key\nuseResponsesApi: false\nrequestOptions:\n  extraBodyProperties:\n    reasoning_effort: high\n    reasoning_budget_tokens: 8192\n    experimental_speed_projection: false\n`);
    if(currentSchema)assert.deepEqual(currentSchema.modelSchema.parse(model),model);
    const api=makeApi(model);
    assert(api);
    const body={model:MODEL,messages:[{role:'user',content:'Fixture only.'}],max_tokens:10923,temperature:0.2,stream:route.includes('background'),tools:[{type:'function',function:TOOL}]};
    if(body.stream){let content='';for await(const event of api.chatCompletionStream(body,new AbortController().signal)) content+=event.choices[0]?.delta?.content||'';assert.equal(content,'fixture response');}
    else assert.equal((await api.chatCompletionNonStream(body,new AbortController().signal)).choices[0].message.content,'fixture response');
    const row=requests.at(-1);assert.equal(row.path,route+'/chat/completions');assert.equal(row.authorization,'Bearer fixture-key');
    assert.deepEqual(row.body.tools,[{type:'function',function:TOOL}]);
    for(const [key,value] of Object.entries({model:MODEL,max_tokens:10923,reasoning_effort:'high',reasoning_budget_tokens:8192,experimental_speed_projection:false,temperature:0.2}))assert.deepEqual(row.body[key],value,key);
    checks.push({client:'continue',path:row.path,complete:true,quality_fields_preserved:true});
  }
  for(const route of ['/v1','/background/v1']){
    const gateway=makeGateway({providerConfigs:[{providerId:'openai-compatible',baseUrl:base+route,apiKey:'fixture-key'}]});
    const events=[];
    for await(const event of await gateway.stream({providerId:'openai-compatible',modelId:MODEL,maxTokens:10923,temperature:0.2,reasoning:{effort:'high',budgetTokens:8192},tools:[{name:TOOL.name,description:TOOL.description,inputSchema:TOOL.parameters}],messages:[{id:'m1',role:'user',content:[{type:'text',text:'Fixture only.'}],createdAt:0}]}))events.push(event);
    const row=requests.at(-1);assert.equal(row.path,route+'/chat/completions');assert.equal(row.authorization,'Bearer fixture-key');
    assert.equal(row.body.model,MODEL);assert.equal(row.body.max_tokens,10923);assert.equal(row.body.reasoning_effort,'high');
    assert.equal(row.body.tools[0].function.name,TOOL.name);assert.deepEqual(row.body.tools[0].function.parameters,TOOL.parameters);
    assert(!('reasoning_budget_tokens' in row.body),'Update documented boundary if exact budget gains support');
    assert(!('experimental_speed_projection' in row.body));
    assert(events.some(e=>JSON.stringify(e).includes('fixture response')));
    assert(!events.some(e=>e.type==='error'),JSON.stringify(events));
    checks.push({client:'cline',path:row.path,complete:true,reasoning_budget_tokens:row.body.reasoning_budget_tokens??null,experimental_speed_projection:row.body.experimental_speed_projection??null,event_types:events.map(e=>e.type)});
  }
  const result={schema:'adaptive-inference.existing-client-transports.v1',passed:true,source_mode:current?'current pinned source bundled with external locked dependencies':'published packages',transport:'actual loopback HTTP with fixture responses; no model',packages:{'@continuedev/openai-adapters':'1.32.0','@cline/llms':'0.0.95'},checks,requests:requests.map(r=>({...r,authorization:'Bearer [fixture key]'})),source_sha256:createHash('sha256').update(fs.readFileSync(import.meta.filename)).digest('hex')};
  if(current)result.source_revisions={continue:'5522c6f44ca0ac3528b37244818fbfa39b5af470',cline:'c7db4bfbd2643425e3c185367cb8c8b4bc468c4f'};
  fs.writeFileSync(current?'current-result.json':'result.json',JSON.stringify(result,null,2)+'\n');console.log(JSON.stringify({passed:true,checks},null,2));
}finally{server.closeAllConnections();await new Promise(r=>server.close(r));}
