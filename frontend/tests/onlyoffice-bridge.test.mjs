import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const source=()=>readFileSync(new URL('../src/editors/bridge-core.js',import.meta.url),'utf8');
function core(){const box={};vm.runInNewContext(source(),box);return box.RixinEvidence;}
test('refuses repeated paragraphs before selecting a quote',()=>{const c=core();assert.equal(c.validate('条款金额100元','100',2,1),'ambiguous')});
test('refuses repeated quotes and stale selection',()=>{const c=core();assert.equal(c.validate('金额100元','100',1,2),'ambiguous');assert.equal(c.validate('金额100元','200',1,1),'not_found')});
test('accepts only contained nonempty exact evidence',()=>{const c=core();assert.equal(c.validate('甲方支付😀100元','😀100',1,1),'located');assert.equal(c.validate('甲方支付100元','',1,1),'not_found')});
