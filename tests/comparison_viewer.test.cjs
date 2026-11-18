const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const {test} = require('node:test');
const {runInNewContext} = require('node:vm');

const html = readFileSync(join(__dirname,'../web/comparison_viewer.html'),'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const settle = () => new Promise(resolve => setImmediate(resolve));

async function viewer({withArchive = true} = {}) {
  const elements = new Map();
  const document = {
    addEventListener(name, start) { this.start = start; },
    getElementById(id) {
      if (!elements.has(id))
        elements.set(id, {id,value:'0',events:{},toggleAttribute(){},
          replaceChildren(...options) { this.options=options; this.value=options[0]?.value??''; },
          stepUp() { this.value=String(Number(this.value)+1); },
          on(event, callback) { this.events[event]=callback; }});
      return elements.get(id);
    }
  };
  const rendered = [], relayout = [], requests = [];
  const coordinates = {latitude:[42],longitude:[2]};
  const forecast = {id:'prediction',name:'prediction.nc',start_utc:'2023-03-24T23:00:00Z'};
  const archives = withArchive ? [{id:'observation',name:'observed.nc',coveredHours:24}] : [];
  const history = {replaceState(_,unused,url) { this.url=url; }};
  runInNewContext(script,{document,URLSearchParams,Float32Array,AbortController,history,
    location:{search:'?forecast=prediction'},
    Option:class {constructor(label,value){this.label=label;this.value=value;}},
    Plotly:{
      async react(map, traces, layout) { rendered.push({id:map.id,data:traces[0].z,scale:layout.coloraxis}); },
      async relayout(map, changes) { relayout.push({id:map.id,changes}); }
    },
    async fetch(url) {
      const request = new URL(url,'http://localhost');
      requests.push(request);
      const index = Number(request.searchParams.get('index') ?? request.searchParams.get('step'));
      return {ok:true,async json() {
        return ({
          '/land.json':{geometries:[]},'/api/graphcast/files':[forecast],
          '/api/graphcast/metadata':{...forecast,...coordinates},'/api/comparison/grid':coordinates,
          '/api/comparison/files':archives
        })[request.pathname];
      },async arrayBuffer() {
        return new Float32Array([index+(request.pathname.includes('graphcast')?20:10)]).buffer;
      }};
    }});
  await document.start();
  await settle();
  return {get:id=>document.getElementById(id),rendered,relayout,requests,history};
}

test('switching interval updates both maps on one timeline and scale',async()=>{
  const view = await viewer();
  assert.deepEqual(view.rendered.slice(-2).map(frame=>[frame.id,frame.data[0][0],frame.scale.cmax]),
    [['archive-map',10,50],['forecast-map',20,50]]);
  assert.equal(view.get('interval').textContent,'2023-03-24 23:00 → 2023-03-25 05:00 UTC');
  assert.equal(view.history.url,'/comparison?forecast=prediction&archive=observation');
  view.get('next').onclick();
  await settle();
  assert.deepEqual(view.rendered.slice(-2).map(frame=>frame.data[0][0]),[11,21]);
  assert.equal(view.get('interval').textContent,'2023-03-25 05:00 → 2023-03-25 11:00 UTC');
  await view.get('archive-map').events.plotly_relayout({'xaxis.range[0]':1,'autosize':true});
  assert.equal(view.relayout[0].id,'forecast-map');
  assert.deepEqual(Object.entries(view.relayout[0].changes),[['xaxis.range[0]',1]]);
});

test('a forecast remains visible when no local archive overlaps',async()=>{
  const view = await viewer({withArchive:false});
  assert.equal(view.get('archive').disabled,true);
  assert.match(view.get('status').textContent,/нет полных шести часов/);
  assert.equal(view.rendered.at(-1).data[0][0],20);
  assert.ok(view.requests.every(request=>request.pathname!=='/api/comparison/frame'));
});
