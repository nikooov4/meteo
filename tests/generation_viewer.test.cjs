const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const {test} = require('node:test');
const {runInNewContext} = require('node:vm');

const html = readFileSync(join(__dirname,'../web/generation_viewer.html'),'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const settle = () => new Promise(resolve => setImmediate(resolve));

async function viewer(state, online=true) {
  const elements=new Map();
  const node=()=>({children:[],value:'',dataset:{},
    append(child) {this.children.push(child);},replaceChildren(...children) {this.children=children;}});
  const get=id=>{if(!elements.has(id))elements.set(id,node());return elements.get(id);};
  const starts=[], timers=[];
  runInNewContext(script,{document:{getElementById:get,createElement:node},
    AbortSignal,setTimeout(callback) { timers.push(callback); },
    async fetch(url, options) {
      if(!online)throw TypeError('Failed to fetch');
      if (url.endsWith('/inputs')) return {ok:true,json:async()=>[
        {id:'daily',name:'archive.nc',archive:'ERA5',prepare:true,preparation:{state}},
        {id:'other',name:'incompatible.nc',archive:'ERA5',prepare:false,compatible:false},
        {id:'sample',name:'example.nc',archive:'Подготовленные входы',compatible:true}
      ]};
      if (url.endsWith('/status')) return {ok:true,json:async()=>({busy:false,step:0,state:'idle',message:'Готово'})};
      if (url.endsWith('/generate')) {
        starts.push(JSON.parse(options.body).id);
        return {ok:true,json:async()=>({busy:true,state:'queued',message:'Прогноз запущен'})};
      }
      throw Error(url);
    }
  });
  await settle();
  const options=()=>get('input-file').children.slice(1).flatMap(group=>group.children.map(option=>option.value));
  return {get,starts,options,connect(){online=true;},setPreparation(value){state=value;},
    async tick(){await timers.shift()();},async select(value){get('input-file').value=value;await get('input-file').onchange();}};
}

test('the archive selection launches generation once, without a separate click',async()=>{
  const page=await viewer('ready');
  assert.deepEqual(page.starts,[]);
  assert.equal(page.get('input-file').value,'');
  assert.match(page.get('input-file').children[1].children[0].textContent,/Готов для ИИ/);
  await page.select('daily');
  assert.deepEqual(page.starts,['daily']);
  assert.equal(page.get('input-file').disabled,true);
  await page.get('generate-form').onsubmit({preventDefault(){}});
  assert.deepEqual(page.starts,['daily']);
});

test('an archive appears only after preparation completes',async()=>{
  const page=await viewer('downloading');
  assert.deepEqual(page.options(),['sample']);
  page.setPreparation('ready');
  await page.tick();
  assert.deepEqual(page.options(),['daily','sample']);
  assert.deepEqual(page.starts,[]);
});

test('a prepared example still starts on demand',async()=>{
  const page=await viewer('available');
  assert.deepEqual(page.options(),['sample']);
  await page.select('sample');
  assert.deepEqual(page.starts,[]);
  await page.get('generate-form').onsubmit({preventDefault(){}});
  assert.deepEqual(page.starts,['sample']);
});

test('the ready list reloads on its own after a connection failure',async()=>{
  const page=await viewer('ready',false);
  assert.match(page.get('error').textContent,/Нет связи с сервером MeteoBridge/);
  assert.equal(page.get('input-file').disabled,true);
  page.connect();
  await page.tick();
  assert.equal(page.get('error').hidden,true);
  assert.equal(page.get('input-file').disabled,false);
  assert.deepEqual(page.options(),['daily','sample']);
});
