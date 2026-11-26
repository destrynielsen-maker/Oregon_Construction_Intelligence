const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync('public/index.html','utf8'),js=html.match(/<script>([\s\S]*)<\/script>/)[1];
const node=()=>({value:'',disabled:false,textContent:'',innerHTML:'',listeners:{},insertAdjacentHTML(_,h){this.innerHTML+=h},addEventListener(e,f){this.listeners[e]=f},querySelector(){return this.span||(this.span=node())}});
const el=Object.fromEntries([...html.matchAll(/\bid="([^"]+)"/g)].map(m=>[m[1],node()]));el.days.value='30';el.minScore.value='30';
const buttons=[...html.matchAll(/data-sort="([^"]+)"/g)].map(m=>({...node(),dataset:{sort:m[1]}}));
const files=Object.fromEntries(['permits','sources','builders'].map(k=>['data/'+k+'.json',JSON.parse(fs.readFileSync('public/data/'+k+'.json','utf8'))]));
class Fixed extends Date{constructor(...a){super(...(a.length?a:['2026-11-26T19:46:00Z']))}static now(){return +new Fixed()}}
let blob,download;
const context={...el,Date:Fixed,Blob,URL:{createObjectURL:b=>{blob=b;return 'blob:testing'},revokeObjectURL(){}},setTimeout:()=>{},
 fetch:async path=>({json:async()=>files[path.split('?')[0]]}),
 document:{getElementById:i=>el[i],querySelectorAll:()=>buttons,body:{appendChild(){}},createElement:()=>({click(){download=this.download},remove(){}})},console};vm.createContext(context);
const change=(k,v)=>{el[k].value=v;el[k].listeners.change()};
(async()=>{
 await vm.runInContext(js,context);
 assert.match(html,/Eastern Oregon: no automated coverage/);
 assert.match(el.updated.textContent,/MT/);
 assert.match(el.sourceCards.innerHTML,/0 records · 0 qualifying.*1,951 records · 1,825 qualifying/);
 assert.match(el.sourceCards.innerHTML,/2026-11-25.*2026-11-17/);
 assert.equal(el.total.textContent,'9,625');
 assert.equal(el.count.textContent,'Showing 1–67 of 67 matching permits');
 change('minScore','0');assert.equal(el.count.textContent,'Showing 1–90 of 90 matching permits');
 change('issuedFrom','2026-09-01');change('issuedTo','2026-09-10');
 assert.equal(el.days.disabled,true);assert.equal(el.count.textContent,'Showing 1–85 of 85 matching permits');
 el.downloadCsv.listeners.click();fs.writeFileSync('csv-sept.csv', await blob.text());
 change('issuedFrom','');change('issuedTo','');assert.equal(el.days.disabled,false);
 assert.equal(el.count.textContent,'Showing 1–90 of 90 matching permits');
 change('days','0');let rows=0;const ranges=[];
 for(;;){rows+=(el.rows.innerHTML.match(/<tr>/g)||[]).length;ranges.push(el.count.textContent);if(el.nextPage.disabled)break;el.nextPage.listeners.click()}
 assert.equal(rows,9625);assert.equal(ranges.length,39);assert.equal(ranges[38],'Showing 9,501–9,625 of 9,625 matching permits');
 el.downloadCsv.listeners.click();assert.equal(download,'oregon-matching-permits.csv');fs.writeFileSync('csv-all.csv', await blob.text());
 assert.equal(vm.runInContext(`csvField('  =9+9')`,context), `"'  =9+9"`);
 assert.equal(vm.runInContext(`csvField('\\t@x')`,context), `"'\t@x"`);
 assert.equal(vm.runInContext(`csvField('x"y')`,context), `"x""y"`);
 assert.equal(vm.runInContext(`csvField(-1)`,context), `"-1"`);
 change('jurisdiction','Bend');assert.equal(el.count.textContent,'Showing 1–250 of 1,825 matching permits');assert.equal(el.pageCount.textContent,'Page 1 of 8');
 change('classification','SINGLE_FAMILY');const family=files['data/permits.json'].permits.filter(p=>p.jurisdiction==='Bend'&&p.classification==='SINGLE_FAMILY').length;assert.ok(el.count.textContent.endsWith(`of ${family.toLocaleString()} matching permits`));
 el.reset.listeners.click();assert.equal(el.count.textContent,'Showing 1–67 of 67 matching permits');assert.equal(el.pageCount.textContent,'Page 1 of 1');
 console.log('PASS: live-fixture DOM harness: scope, health, Mountain time, defaults, custom dates, page traversal, filtered CSV, CSV escaping, jurisdiction/type filters and reset.');
})().catch(e=>{console.error(e);process.exitCode=1});
