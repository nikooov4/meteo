const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const {test} = require('node:test');
const {runInNewContext} = require('node:vm');
const html = readFileSync(join(__dirname,'../web/archive_viewer.html'),'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const settle = () => new Promise(resolve => setImmediate(resolve));

async function viewer({initialState='available',confirm=true}={}) {
  const elements = new Map(), requests = [], held = new Map(), confirmations=[];
  const element = () => ({children:[],value:'',hidden:false,disabled:false,dataset:{},style:{},textContent:'',
    append(...children) {this.children.push(...children);}, appendChild(child) {this.children.push(child);},
    replaceChildren(...children) {this.children=children;}, setAttribute() {}, querySelectorAll() {return [];}});
  const get = id => {if (!elements.has(id)) elements.set(id,element()); return elements.get(id);};
  get('source').value='amazon'; get('month').value='0';
  const sources = ['amazon','google'].map(id => ({id,label:id,description:'Original '+id,archive_url:'https://'+id+'.example/archive'}));
  const states = {amazon:'available',google:initialState};
  runInNewContext(script, {document:{getElementById:get,createElement:element,createTextNode:text=>({textContent:text})},
    window:{confirm(message) {confirmations.push(message);return confirm;}},
    URLSearchParams, Intl, Date, setTimeout:()=>1,clearTimeout() {},
    async fetch(url,options) {
      requests.push({url,options});
      const source = new URL(url,'http://localhost').searchParams.get('source');
      if (source && held.has(source)) await held.get(source);
      let data;
      if (url.endsWith('/settings')) data={directory:'data',first_year:1940,last_year:2026,default_year:2023,sources};
      else if (url.endsWith('/local')) data={files:states.google==='downloaded'?[{id:'google-id',name:'google.nc',format:'NetCDF',bytes:100}]:[]};
      else if (url.includes('/files?')) data=[{key:source+':object',name:source+'.nc',format:'NetCDF',provider:'Archive '+source,
        start_utc:'2023-01-01T23:00:00Z',end_utc:'2023-01-02T23:00:00Z',bytes:100,received_bytes:100,state:states[source],
        downloaded:states[source]==='downloaded',local_id:states[source]==='downloaded'?source+'-id':null}];
      else if (url.endsWith('/delete')) {states.google='available';data={deleted:true};}
      else {states.google='validating'; data={status:'queued'};}
      return {ok:true,json:async()=>data};
    },
  });
  await settle(); await settle();
  const text = node => node.textContent+' '+node.children?.map(text).join(' ');
  return {get,requests,held,text,confirmations,
    async source(value) {get('source').value=value; get('source').onchange(); await settle(); await settle();}};
}

test('the download catalog switches between two original NetCDF archives and links to the selected one',async()=>{
  const page=await viewer();
  assert.match(page.requests.find(request=>request.url.includes('/files?')).url,/source=amazon/);
  await page.source('google');
  assert.equal(page.get('source-description').textContent,'Original google');
  assert.equal(page.get('source-archive').href,'https://google.example/archive');
  assert.match(page.text(page.get('files')),/google.nc · NetCDF · Archive google/);
  const button=page.get('files').children[0].children[1].children[2];
  await button.onclick();
  const post=page.requests.find(request=>request.url.endsWith('/download'));
  assert.deepEqual(JSON.parse(post.options.body),{key:'google:object'});
  assert.match(page.text(page.get('files')),/Проверка файла/);
  assert.doesNotMatch(page.text(page.get('files')),/Подготовка/);
});

test('a late response from a previous archive cannot overwrite the new catalog',async()=>{
  const page=await viewer();
  let release;
  page.held.set('google',new Promise(resolve=>{release=resolve;}));
  await page.source('google');
  await page.source('amazon');
  release(); await settle(); await settle();
  assert.match(page.text(page.get('files')),/amazon.nc/);
  assert.doesNotMatch(page.text(page.get('files')),/google.nc/);
  assert.equal(page.get('source-description').textContent,'Original amazon');
  assert.equal(page.get('source-archive').href,'https://amazon.example/archive');
});

test('the site download selector comes first and manual import remains available',()=>{
  assert.ok(html.indexOf('id="catalog-title"')<html.indexOf('id="import-title"'));
  assert.match(html,/id="source"[\s\S]*?value="amazon"[\s\S]*?value="google"/);
  assert.match(html,/id="import-files"[^>]*multiple[^>]*accept=".nc,.grib/);
  assert.doesNotMatch(html,/Или добавить свои файлы с компьютера|Открыть карту с добавленными файлами|value="grib"|value="geotiff"/);
});

test('deleting a downloaded file sends its local id and refreshes both lists',async()=>{
  const page=await viewer({initialState:'downloaded'});
  await page.source('google');
  const button=page.get('files').children[0].children[1].children[3];
  await button.onclick();
  assert.equal(page.confirmations.length,1);
  assert.deepEqual(JSON.parse(page.requests.find(request=>request.url.endsWith('/delete')).options.body),{id:'google-id'});
  assert.match(page.text(page.get('files')),/Не скачано/);
  assert.equal(page.get('local-files').children.length,0);
});

test('cancelling the deletion dialog keeps the file',async()=>{
  const page=await viewer({initialState:'downloaded',confirm:false});
  await page.source('google');
  await page.get('files').children[0].children[1].children[3].onclick();
  assert.ok(!page.requests.some(request=>request.url.endsWith('/delete')));
  assert.match(page.text(page.get('files')),/Скачано/);
});
