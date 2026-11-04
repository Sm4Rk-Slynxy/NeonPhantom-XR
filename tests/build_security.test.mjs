import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {realpathSync} from 'node:fs';
const require=createRequire(new URL('../frontend/package.json',import.meta.url));
const fromPlugin=createRequire(require.resolve('@sveltejs/vite-plugin-svelte'));
const merge=fromPlugin('deepmerge');

test('Svelte plugin resolves the patched local module',()=>{
  assert.equal(realpathSync(fromPlugin.resolve('deepmerge')),realpathSync(new URL('../frontend/vendor/deepmerge-safe/index.cjs',import.meta.url)));
});

function assertUnpoisoned(result){
  assert.equal(Object.getPrototypeOf(result),Object.prototype);
  assert.equal(result.compromised,undefined);
  assert.equal({}.compromised,undefined);
}

test('poisoned target cannot poison a returned object',()=>{
  const payload=JSON.parse('{"__proto__":{"compromised":true}}');
  const result=merge(payload,{});
  assertUnpoisoned(result);
  assert.equal(Object.hasOwn(result,'__proto__'),true);
});

test('null-prototype target cannot bypass source-key validation',()=>{
  const result=merge(Object.create(null),JSON.parse('{"__proto__":{"compromised":true}}'));
  assertUnpoisoned(result);
  assert.equal(result.__proto__.compromised,true); // own data, never inherited configuration.
});

test('nested and constructor/prototype payloads stay inert',()=>{
  const result=merge({options:JSON.parse('{"__proto__":{"compromised":true}}')},
    JSON.parse('{"options":{"enabled":true},"constructor":{"prototype":{"compromised":true}}}'));
  assertUnpoisoned(result);assertUnpoisoned(result.options);
  assert.equal(result.options.enabled,true);
});

test('normal Svelte config merging retains values, functions, and array replacement',()=>{
  const handler=()=>{};const symbol=Symbol('setting');
  const base={compilerOptions:{dev:true,css:'external'},extensions:['.svelte'],onwarn:handler,[symbol]:{a:1}};
  const source={compilerOptions:{dev:false},extensions:['.custom'],[symbol]:{b:2}};
  const result=merge(base,source,{arrayMerge:(target,source)=>source??target});
  assert.deepEqual(result.compilerOptions,{dev:false,css:'external'});
  assert.deepEqual(result.extensions,['.custom']);assert.equal(result.onwarn,handler);
  assert.deepEqual(result[symbol],{a:1,b:2});assert.equal(base.compilerOptions.dev,true);
});

test('upstream array, custom merge and special object behavior remains available',()=>{
  const date=new Date(0),pattern=/demo/;
  assert.deepEqual(merge({list:[1]},{list:[2]}).list,[1,2]);
  assert.deepEqual(merge.all([{a:1},{b:2}]),{a:1,b:2});
  assert.equal(merge({},{date,pattern}).date,date);
  assert.equal(merge({},{pattern}).pattern,pattern);
  assert.equal(merge({item:{count:1}},{item:{count:2}},
    {customMerge:key=>key==='item'?(a,b)=>({count:a.count+b.count}):undefined}).item.count,3);
});
