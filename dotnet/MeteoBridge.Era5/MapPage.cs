using System.Text.Json;

namespace MeteoBridge.Era5;

internal static class MapPage
{
    public static string Create(Era5Index index)
    {
        var first = Era5Index.Iso(index.Start);
        var end = Era5Index.Iso(index.End);
        var info = new
        {
            bbox = index.Bbox, intervals = new[] { new[] { first, Era5Index.Iso(index.Start + 3600) } },
            origin = "original", label = "LSP · " + string.Join(" / ", index.Sources.Select(source => source.Format).Distinct()), grid_shape = new[] { index.Latitude.Length, index.Longitude.Length },
            member = 0, archive_api = "/map-archive", first_hour = 0, manifest_sha256 = index.Sha, downloads_available = true,
            initial_selection = new { first_hour = 0, hours = index.Hours, member = 0, start_utc = first, end_utc = end }
        };
        var template = File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "Assets", "map_viewer.html"));
        var plot = """
            <div id="era5-plot"></div>
            <script src="/plotly.min.js"></script>
            <script>
            document.addEventListener('DOMContentLoaded', async () => {
              try {
                const [grid, land] = await Promise.all([
                  fetch('/grid').then(response => response.json()),
                  fetch('/land.json').then(response => response.json())
                ]);
                const longitude = [], latitude = [];
                for (const geometry of land.geometries) {
                  const polygons = geometry.type === 'Polygon' ? [geometry.coordinates] : geometry.coordinates;
                  for (const polygon of polygons) for (const ring of polygon) {
                    let previous = null;
                    for (const [lon, lat] of ring) {
                      if (previous !== null && Math.abs(lon-previous)>180) { longitude.push(null); latitude.push(null); }
                      longitude.push(lon); latitude.push(lat); previous=lon;
                    }
                    longitude.push(null); latitude.push(null);
                  }
                }
                const bbox = window.meteoMapInfo.bbox;
                const plot = document.getElementById('era5-plot');
                await Plotly.newPlot(plot, [
                  {type:'heatmap', x:grid.longitude, y:grid.latitude,
                   z:grid.latitude.map(() => grid.longitude.map(() => null)),
                   coloraxis:'coloraxis', zsmooth:false, connectgaps:false, hoverongaps:false,
                   hovertemplate:'%{y:.2f}°N, %{x:.2f}°E<br>%{z:.4f} mm за час<extra></extra>'},
                  {type:'scatter', x:longitude, y:latitude, mode:'lines',
                   line:{color:'#49556b', width:.8}, hoverinfo:'skip', showlegend:false}
                ], {
                  title:{text:'Осадки · LSP', font:{size:15}, x:.01},
                  font:{family:'Segoe UI, Arial'}, dragmode:'pan', uirevision:'keep-map-zoom',
                  paper_bgcolor:'#ffffff', plot_bgcolor:'#edf5fa',
                  margin:{l:8,r:68,t:62,b:4},
                  coloraxis:{cmin:0,cmax:50,colorbar:{title:{text:'мм за час',font:{size:10}},thickness:9,len:.82,outlinewidth:0}},
                  xaxis:{visible:false,range:bbox.slice(0,2),domain:[0,1],minallowed:bbox[0],maxallowed:bbox[1]},
                  yaxis:{visible:false,range:bbox.slice(2,4),domain:[0,1],minallowed:bbox[2],maxallowed:bbox[3]}
                }, {displayModeBar:false,responsive:false,scrollZoom:true,doubleClick:false});
                window.initMeteoMap(plot);
              } catch(error) { document.getElementById('map-status').textContent=error.message; }
            }, {once:true});
            </script>
            """;
        return template.Replace("__MAP_INFO_JSON__", JsonSerializer.Serialize(info)).Replace("<!-- MAP_PLOT -->", plot);
    }
}
