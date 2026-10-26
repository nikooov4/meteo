const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const {test} = require('node:test');
const {runInNewContext} = require('node:vm');
const html = readFileSync(join(__dirname,'../web/archive_viewer.html'),'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const settle = () => new Promise(resolve => setImmediate(resolve));

async function viewer({initialState='available',cdsState='available',cdsError=null,cdsErrorCode=null,cdsConfigured=false,
  cdsBytes=0,cdsReceived=0,cdsEstimate=0,cdsElapsed=0,confirm=true}={}) {
  const elements = new Map(), requests = [], held = new Map(), confirmations=[];
  const element = () => ({children:[],value:'',hidden:false,disabled:false,dataset:{},style:{},textContent:'',
    append(...children) {this.children.push(...children);}, appendChild(child) {this.children.push(child);},
    replaceChildren(...children) {this.children=children;}, attributes:{},
    setAttribute(name,value) {this.attributes[name]=value;}, focus() {this.focused=true;}, querySelectorAll() {return [];}});
  const get = id => {if (!elements.has(id)) elements.set(id,element()); return elements.get(id);};
  get('source').value='amazon'; get('month').value='0';
  const sources = ['amazon','google','cds'].map(id => ({id,label:id,format:id==='cds'?'GRIB':'NetCDF',description:'Original '+id,archive_url:'https://'+id+'.example/archive'}));
  const states = {amazon:'available',google:initialState,cds:cdsState};
  runInNewContext(script, {document:{getElementById:get,createElement:element,createTextNode:text=>({textContent:text})},
    window:{confirm(message) {confirmations.push(message);return confirm;}},
    URLSearchParams, Intl, Date, setTimeout:()=>1,clearTimeout() {},
    async fetch(url,options) {
      requests.push({url,options});
      const source = new URL(url,'http://localhost').searchParams.get('source');
      if (source && held.has(source)) await held.get(source);
      let data;
      if (url.endsWith('/settings')) data={directory:'data',first_year:1940,last_year:2026,default_year:2023,sources,cds_configured:cdsConfigured};
      else if (url.includes('/files?')) data=[{key:source+':object',name:source+(source==='cds'?'.grib':'.nc'),format:source==='cds'?'GRIB':'NetCDF',provider:'Archive '+source,
        start_utc:'2023-01-01T23:00:00Z',end_utc:'2023-01-02T23:00:00Z',bytes:source==='cds'?cdsBytes:100,
        received_bytes:source==='cds'?cdsReceived:0,estimated_bytes:source==='cds'?cdsEstimate:0,
        elapsed_seconds:source==='cds'?cdsElapsed:0,source,state:states[source],
        error:source==='cds'?cdsError:null,error_code:source==='cds'?cdsErrorCode:null,
        downloaded:states[source]==='downloaded',local_id:states[source]==='downloaded'?source+'-id':null}];
      else if (url.endsWith('/cds-token')) data={configured:!!JSON.parse(options.body).token};
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

test('CDS requires a token, clears the password and enables GRIB downloads',async()=>{
  const page=await viewer(); await page.source('cds');
  assert.equal(page.get('cds-credentials').hidden,false);
  assert.equal(page.get('files').children[0].children[1].children[2].disabled,true);
  assert.match(page.text(page.get('files')),/cds.grib · GRIB/);
  assert.match(page.text(page.get('files')),/Размер после подготовки/);
  assert.doesNotMatch(page.text(page.get('files')),/NaN|Infinity/);
  page.get('cds-token').value='test-token';
  await page.get('cds-token-editor').onsubmit({preventDefault(){}});
  assert.equal(page.get('cds-token').value,'');
  assert.equal(page.get('files').children[0].children[1].children[2].disabled,false);
  assert.match(page.get('cds-status').textContent,/Токен сохранён/);
  assert.equal(page.get('cds-token-editor').hidden,true);
  assert.equal(page.get('cds-token-summary').hidden,false);
  assert.doesNotMatch(page.get('cds-status').textContent,/Можно отправлять/);
  await page.source('amazon'); assert.equal(page.get('cds-credentials').hidden,true);
});

test('the archive selector shows the format supplied by each provider',async()=>{
  const page=await viewer();
  assert.deepEqual(page.get('source').children.map(option=>option.textContent),['amazon · NC','google · NC','cds · GRIB']);
});

test('a configured token starts collapsed and the pencil opens editing without changing it',async()=>{
  const page=await viewer({cdsConfigured:true}); await page.source('cds');
  assert.equal(page.get('cds-token-editor').hidden,true);
  assert.equal(page.get('cds-token-summary').hidden,false);
  page.get('cds-edit-token').onclick();
  assert.equal(page.get('cds-token-editor').hidden,false);
  assert.equal(page.get('cds-token-summary').hidden,true);
  assert.equal(page.get('cds-token').focused,true);
  page.get('cds-token').value='unsaved-token';
  page.get('cds-cancel-token').onclick();
  assert.equal(page.get('cds-token').value,'');
  assert.equal(page.get('cds-token-editor').hidden,true);
  assert.equal(page.get('cds-token-summary').hidden,false);
  assert.ok(!page.requests.some(request=>request.url.endsWith('/cds-token')));
  assert.equal(page.get('files').children[0].children[1].children[2].disabled,false);
});

test('replacing a token collapses the editor again and clearing it reopens the input',async()=>{
  const page=await viewer({cdsConfigured:true}); await page.source('cds');
  page.get('cds-edit-token').onclick(); page.get('cds-token').value='replacement-token';
  await page.get('cds-token-editor').onsubmit({preventDefault(){}});
  assert.equal(page.get('cds-token-editor').hidden,true);
  assert.equal(page.get('cds-credentials').dataset.collapsed,'true');
  page.get('cds-edit-token').onclick();
  await page.get('cds-token-editor').onsubmit({preventDefault(){}});
  assert.equal(page.get('cds-token-editor').hidden,false);
  assert.equal(page.get('cds-cancel-token').hidden,true);
  assert.equal(page.get('files').children[0].children[1].children[2].disabled,true);
});

test('CDS licence refusal links to the dataset licence section',async()=>{
  const page=await viewer({cdsState:'failed',cdsError:'Не приняты условия ERA5',cdsErrorCode:'licence_required'});
  await page.source('cds');
  const error=page.get('files').children[0].children[2];
  assert.match(page.text(error),/Принять условия ERA5/);
  const link=error.children[1];
  assert.equal(link.href,'https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels?tab=download#manage-licences');
  assert.equal(link.target,'_blank');
});

test('a queued CDS request can be stopped before its size is known',async()=>{
  const page=await viewer({cdsState:'waiting'}); await page.source('cds');
  const button=page.get('files').children[0].children[1].children[2];
  assert.equal(button.disabled,false); assert.equal(button.textContent,'Остановить');
  assert.match(page.text(page.get('files')),/В очереди CDS/);
  await button.onclick();
  assert.deepEqual(JSON.parse(page.requests.find(request=>request.url.endsWith('/cancel')).options.body),{key:'cds:object'});
});

test('CDS preparation shows estimated size and elapsed waiting time without a fake percentage',async()=>{
  const page=await viewer({cdsState:'waiting',cdsEstimate:49838112,cdsElapsed:125}); await page.source('cds');
  assert.match(page.text(page.get('files')),/≈49.8 MB/);
  assert.match(page.text(page.get('files')),/2 мин 5 с/);
  assert.match(page.text(page.get('files')),/Передача начнётся автоматически/);
  assert.doesNotMatch(page.text(page.get('files')),/\d+%/);
  const status=page.get('files').children[0].children[1].children[1];
  const progress=status.children.find(child=>child.attributes?.['aria-label']?.startsWith('В очереди CDS'));
  assert.equal(progress.value,''); // the test DOM's untouched progress value
});

test('CDS transfer shows the true percentage and actual received megabytes',async()=>{
  const page=await viewer({cdsState:'downloading',cdsBytes:50000000,cdsReceived:12500000,cdsEstimate:90000000});
  await page.source('cds');
  const text=page.text(page.get('files'));
  assert.match(text,/50.0 MB/); assert.match(text,/25% · 12.5 \/ 50.0 MB/);
  assert.doesNotMatch(text,/≈|90.0/);
});

test('completed CDS downloads have a single downloaded button without a duplicate status',async()=>{
  const page=await viewer({cdsState:'downloaded',cdsBytes:49838112,cdsReceived:49838112}); await page.source('cds');
  const content=page.text(page.get('files'));
  assert.equal((content.match(/Скачано/g)||[]).length,1);
  assert.doesNotMatch(content,/100%|✓/);
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

test('the archive page provides downloads without the manual import panel',()=>{
  assert.match(html,/id="source"[\s\S]*?value="amazon"[\s\S]*?value="google"/);
  assert.doesNotMatch(html,/Добавить свои файлы|import-files|import-queue|drop-zone|queueImports|loadLocal/);
});

test('deleting a downloaded file sends its local id and refreshes the catalog',async()=>{
  const page=await viewer({initialState:'downloaded'});
  await page.source('google');
  const button=page.get('files').children[0].children[1].children[2];
  await button.onclick();
  assert.equal(page.confirmations.length,1);
  assert.deepEqual(JSON.parse(page.requests.find(request=>request.url.endsWith('/delete')).options.body),{id:'google-id'});
  assert.match(page.text(page.get('files')),/Не скачано/);
  assert.ok(!page.requests.some(request=>request.url.endsWith('/local')));
});

test('cancelling the deletion dialog keeps the file',async()=>{
  const page=await viewer({initialState:'downloaded',confirm:false});
  await page.source('google');
  await page.get('files').children[0].children[1].children[2].onclick();
  assert.ok(!page.requests.some(request=>request.url.endsWith('/delete')));
  assert.match(page.text(page.get('files')),/Скачано/);
});
