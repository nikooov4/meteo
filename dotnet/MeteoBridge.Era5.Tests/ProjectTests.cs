using System.Text.RegularExpressions;
using System.Xml.Linq;

namespace MeteoBridge.Era5.Tests;

public sealed class ProjectTests
{
    [Fact]
    public void SolutionLinksAndPackagedAssetsUseExistingFiles()
    {
        var root = TestDirectory.Root;
        var solution = File.ReadAllText(Path.Combine(root,"MeteoBridge.sln"));
        var links = Regex.Matches(solution, @"(?m)^\s+([^=\r\n]+?) = \1\s*$").Select(match=>match.Groups[1].Value.Trim())
            .Where(path=>!path.Contains('|') && !path.StartsWith('{')).ToArray();
        Assert.Equal(links.Length,links.Distinct(StringComparer.OrdinalIgnoreCase).Count());
        Assert.All(links,path=>Assert.True(File.Exists(Path.Combine(root,path.Replace('\\',Path.DirectorySeparatorChar))),path));
        Assert.Contains("MeteoBridge.Era5.Tests.csproj", solution);
        Assert.Contains(@"web\comparison_viewer.html",solution);
        var project=XDocument.Load(Path.Combine(root,"dotnet","MeteoBridge.Era5","MeteoBridge.Era5.csproj"));
        Assert.All(project.Descendants("Content"),node=>
        {
            var path=node.Attribute("Include")!.Value;
            Assert.DoesNotContain("research",path);
            Assert.DoesNotContain(".venv",path);
        });
        Assert.False(Directory.Exists(Path.Combine(root,"research")));
        Assert.True(File.Exists(Path.Combine(root,"workers","graphcast","archive_input.py")));
        Assert.True(File.Exists(Path.Combine(root,"workers","graphcast","service.py")));
    }

    [Fact]
    public async Task PagesAndArchiveReaderWorkFromBundledFilesWithoutPython()
    {
        using var folder = new TestDirectory();
        var binary = Path.GetDirectoryName(TestSite.Binary)!;
        var deploy = Directory.CreateDirectory(folder.At("published")).FullName;
        foreach (var directory in Directory.GetDirectories(binary,"*",SearchOption.AllDirectories))
            Directory.CreateDirectory(Path.Combine(deploy,Path.GetRelativePath(binary,directory)));
        foreach (var path in Directory.EnumerateFiles(binary,"*",SearchOption.AllDirectories))
            File.Copy(path, Path.Combine(deploy,Path.GetRelativePath(binary,path)));
        RasterFixtures.Flat(folder.At("era5","archive.nc"),new DateTimeOffset(2023,1,1,7,0,0,TimeSpan.Zero),24,2);
        await using var site = await TestSite.StartAsync(folder,binary:Path.Combine(deploy,Path.GetFileName(TestSite.Binary)),root:deploy);
        Assert.Equal(deploy,(await site.Get("/health")).GetProperty("project_root").GetString());
        foreach (var route in new[] {"/","/downloads","/generation","/comparison","/plotly.min.js","/land.json"})
        {
            using var response = await site.Client.GetAsync(route);
            response.EnsureSuccessStatusCode();
            if (route is "/" or "/downloads" or "/generation" or "/comparison")
                Assert.Equal("no-store",response.Headers.CacheControl?.ToString());
        }
        Assert.All(await ArchiveReadingTests.Values(site,0),value=>Assert.Equal(2,value,4));
        Assert.False((await site.Get("/api/graphcast/status")).GetProperty("runtime_available").GetBoolean());
    }

    [Fact]
    public async Task OccupiedPortFallsBackToAnotherLoopbackPort()
    {
        using var folder = new TestDirectory();
        await using var occupied = await TestRemote.StartAsync(_=>{});
        await using var site = await TestSite.StartAsync(folder,["--urls",occupied.Url]);
        Assert.NotEqual(new Uri(occupied.Url).Port,site.Client.BaseAddress!.Port);
        Assert.Equal("csharp",(await site.Get("/health")).GetProperty("engine").GetString());
    }
}
