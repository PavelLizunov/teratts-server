import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';
const source=await readFile(new URL('../lib/client.js',import.meta.url),'utf8');
const start=source.indexOf('function synthesizeWithDeadline(');
const end=source.indexOf('\nconst SECOND_SPEECH_CHUNK_CHARS',start);
const synthesize=new Function('SPEECH_RPC_TIMEOUT_MS',source.slice(start,end)+'\nreturn synthesizeWithDeadline;')(65000);

test('lost RPC settles at deadline and aborts downstream',async()=>{
 let signal;const parent=new AbortController();
 await assert.rejects(synthesize({synthesize(_text,s){signal=s;return new Promise(()=>{});}},'тест',parent.signal,15),/timed out/);
 assert.equal(signal.aborted,true);
});
test('Stop settles even if RPC ignores cancellation; late success stays ignored',async()=>{
 let done,downstream;const parent=new AbortController();let calls=0;
 const result=synthesize({synthesize(_text,s){calls++;downstream=s;return new Promise(resolve=>done=resolve);}},'тест',parent.signal,1000);
 await Promise.resolve();parent.abort(new Error('stopped'));
 await assert.rejects(result,/stopped/);assert.equal(downstream.aborted,true);
 done({audioBase64:'late'});assert.equal(calls,1);
});
test('already cancelled request never invokes RPC; success clears deadline',async()=>{
 const parent=new AbortController();parent.abort();let calls=0;
 const voice={synthesize(){calls++;return Promise.resolve('audio');}};
 await assert.rejects(synthesize(voice,'тест',parent.signal,15));assert.equal(calls,0);
 assert.equal(await synthesize(voice,'тест',new AbortController().signal,15),'audio');
 assert.equal(calls,1);
});
test('synchronous RPC exceptions settle and do not leak timer',async()=>{
 await assert.rejects(synthesize({synthesize(){throw new Error('RPC rejected');}},'тест',new AbortController().signal,1000),/RPC rejected/);
});
