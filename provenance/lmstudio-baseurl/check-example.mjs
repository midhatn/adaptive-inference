import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import net from "node:net";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

const revision = "8c7159be3ffe364af10aa8ae6f5a7570e9402089";
const sourcePath = "1_developer/3_openai-compat/index.mdx";
const sourceBlob = "0bca40d4c85c5f8daf78f3e4aaaa9f0b1b0e7784";
const sourceSha256 = "e6c318bb3da455725f836c1a833e0ac2b42897a12751ba49a90199d600f41f31";
const before = readFileSync("fixtures/before.ts","utf8");
assert.equal(createHash("sha256").update(before).digest("hex"),"32a59b55435efc3e80e7a69d4642260eba3d34d93eb437b2db88423f979d85c7");
assert.equal(before.match(/baseUrl:/g)?.length, 1);
const after = before.replace("baseUrl:", "baseURL:");
writeFileSync("before.ts", before);
writeFileSync("after.ts", after);
writeFileSync("before.mjs", before + "export default client;\n");
writeFileSync("after.mjs", after + "export default client;\n");
const env = {...process.env, OPENAI_API_KEY:"not-a-secret-local-fixture"};
delete env.OPENAI_BASE_URL;
function typecheck(file, expected) {
  const output = spawnSync(process.execPath, ["node_modules/typescript/bin/tsc", "--noEmit", "--strict", "--module", "nodenext", "--target", "ES2022", "--skipLibCheck", "--types", "node", file], {encoding:"utf8", env, timeout:30000});
  const text = (output.stdout || "") + (output.stderr || "");
  writeFileSync(file + ".typecheck.txt", text);
  assert.equal(output.status, expected);
  return {exit_code:output.status, diagnostic:text.trim()};
}
const brokenType = typecheck("before.ts",1);
assert.match(brokenType.diagnostic, /baseUrl/);
assert.match(brokenType.diagnostic, /baseURL/);
const correctedType = typecheck("after.ts",0);

process.env.OPENAI_API_KEY = "not-a-secret-local-fixture";
delete process.env.OPENAI_BASE_URL;
let socketAttempts = 0;
const originalConnect = net.Socket.prototype.connect;
net.Socket.prototype.connect = function() { socketAttempts++; throw new Error("Network sockets are disabled in this example test"); };
const requests = [];
globalThis.fetch = async (input, init) => {
  const url = typeof input === "string" || input instanceof URL ? String(input) : input.url;
  const body = init?.body ? JSON.parse(init.body) : null;
  requests.push({url, method:init?.method, body});
  return new Response(JSON.stringify({id:"fixture-completion",object:"chat.completion",created:0,model:body.model,choices:[{index:0,message:{role:"assistant",content:"fixture only"},finish_reason:"stop"}],usage:{prompt_tokens:1,completion_tokens:1,total_tokens:2}}),{status:200,headers:{"content-type":"application/json"}});
};
const payload = {
  model:"qwen3.8-flash-next-iq3_s-adaptive-media-beta",
  messages:[{role:"user",content:"Fixture; do not dispatch to a model."}],
  max_tokens:10923,
  reasoning_effort:"high",
  reasoning_budget_tokens:8192,
  experimental_speed_projection:false,
  temperature:0.2,
};
try {
  const bad = (await import(pathToFileURL(resolve("before.mjs")).href)).default;
  const good = (await import(pathToFileURL(resolve("after.mjs")).href)).default;
  await bad.chat.completions.create(payload);
  await good.chat.completions.create(payload);
  assert.equal(requests[0].url,"https://api.openai.com/v1/chat/completions");
  assert.equal(requests[1].url,"http://localhost:1234/v1/chat/completions");
  for (const request of requests) assert.deepEqual(request.body,payload);
  assert.equal(socketAttempts,0);
} finally {
  net.Socket.prototype.connect = originalConnect;
}
const sha = text => createHash("sha256").update(text).digest("hex");
const lock = JSON.parse(readFileSync("package-lock.json","utf8"));
const result = {
  schema:"lmstudio.openai-example-check.v1", passed:true,
  source:{repository:"lmstudio-ai/docs",revision,path:sourcePath,git_blob:sourceBlob,sha256:sourceSha256,verification:"Original document verified during extraction; this test pins the extracted constructor bytes"},
  sdk:{package:"openai",version:lock.packages["node_modules/openai"].version,integrity:lock.packages["node_modules/openai"].integrity,npm_git_head:"d02d4de77ea7a6f82325c02e6f44deb34ee3992c",source_reference_revision:"8e32d2df55d99fdcd5be8862d4815007f7ad076f"},
  compiler:{typescript:lock.packages["node_modules/typescript"].version,node:process.version},
  examples:{before_sha256:sha(before),after_sha256:sha(after)},
  typecheck:{original:brokenType,corrected:correctedType},
  fake_transport:{original_url:requests[0].url,corrected_url:requests[1].url,body_preserved:true,requests:requests.length,socket_attempts:socketAttempts},
  duplicate_review:{pr139:{state:"merged",merge_commit:"d712bc9064b372b7974d14a94a43ed0c3ae36ec9",related_file:"1_developer/3_openai-compat/index.md",change:"endpoint table only; no constructor option change"},all_state_searches:["baseURL","baseUrl"],matching_search_results:0},
  scope:"Exact documentation constructor extracted and typechecked against pinned real SDK; generated chat requests intercepted by fake fetch; no model, LM Studio server or external HTTP request",
};
writeFileSync("result.json",JSON.stringify(result,null,2)+"\n");
console.log(JSON.stringify(result,null,2));

