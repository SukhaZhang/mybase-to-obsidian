//sValidation=nyfjs
//sCaption=Export database to Obsidian Markdown ...
//sHint=导出当前 myBase 数据库为 Obsidian 友好的 Markdown 中间格式（frontmatter + _index.md）
//sCategory=MainMenu.Share
//sCondition=CURDB; OUTLINE; CURINFOITEM
//sID=p.ExportObsidianMd
//sAppVerMin=7.0
//sAuthor=mybase-to-obsidian

/////////////////////////////////////////////////////////////////////
// myBase → Obsidian 迁移（第一步：导出）
//
// 用法：
//   1. 在 myBase 中打开要导出的数据库（.nyf / .leo）
//   2. Share 菜单 → Export database to Obsidian Markdown ...
//   3. 选择导出目录（多个数据库可导出到同一目录）
//   4. 每个数据库生成一个子目录，默认用数据库文件名命名：
//        <导出目录>/<数据库名>/分类目录/_index.md
//        <导出目录>/<数据库名>/.../笔记目录/index.md
//
// 然后用 mybase2obsidian.py 转换成 Obsidian Vault。
//
// 导出格式（frontmatter 与历史版本兼容）：
//   ---
//   title: "标题"
//   source: mybase
//   database: "work2"
//   folder: "分类 > 层级 > 标题"
//   ---
//   # 标题
//   <原始正文，保留 HTML>
//
// 注意：正文保留 myBase 内的原始内容（HTML/纯文本），
//       第二步由 Python 脚本转成 Markdown。
/////////////////////////////////////////////////////////////////////

// ================== 可配置项（一般无需修改） ==================
var CONFIG = {
    // frontmatter 的 source 字段（用于区分来源，可自定义）
    source: 'mybase',

    // 导出子目录名。留空 = 自动使用数据库文件名（推荐）
    topDir: ''
};
// ==============================================================

var _trim = function(s){ return (s||'').replace(/^\s+|\s+$/g, ''); };

// 目录/文件名清理：替换 Windows 非法字符，保留空格与常见符号
var _validate_name = function(s){
    s = (s||'').replace(/[\\\/\:\*\?\"\<\>\|]/g, ' ');
    s = s.replace(/\s+/g, ' ');
    s = _trim(s);
    if(!s) s = 'Untitled';
    if(s.length > 128) s = s.substr(0, 128);
    return s;
};

try{

    var xNyf = new CNyfDb(-1);
    if(!xNyf.isOpen()){
        alert('当前没有打开的数据库，请先在 myBase 中打开要导出的数据库。');
        throw 'cancel';
    }

    if(plugin.isContentEditable()) plugin.commitCurrentChanges();

    // 选择导出目标目录（记住上次选择）
    var sCfgKey = 'ExportObsidianMd.sDir';
    var sDstDir = platform.browseForFolder('选择导出目标目录（多个数据库可导出到同一目录）', localStorage.getItem(sCfgKey));
    if(!sDstDir) throw 'cancel';
    localStorage.setItem(sCfgKey, sDstDir);

    // 数据库文件名（去扩展名）作为 database 字段与默认子目录名
    var sDbFile = xNyf.getDbFile();
    var sDbName = new CLocalFile(sDbFile).getTitle();
    if(!sDbName) sDbName = 'database';

    // 顶层子目录：CONFIG.topDir 优先，否则用数据库名
    var sTopDir = CONFIG.topDir ? _validate_name(CONFIG.topDir) : _validate_name(sDbName);

    var sRoot = plugin.getCurInfoItem(-1) || plugin.getDefRootContainer();

    // ---------- 第一遍：遍历收集结构 ----------
    var listNodes = [];     // [{ssg,title,level,folder,hasContent,isFolder}]
    var mapChildren = {};   // 父 folder 路径 -> [子标题]
    var vTitle = [];        // vTitle[iLevel] = 第 iLevel 层标题（iLevel=0 为数据库根）

    xNyf.traverseOutline(sRoot, true, function(sSsgPath, iLevel){
        var sTitle = xNyf.getFolderHint(sSsgPath);
        if(!sTitle) sTitle = 'Untitled';

        vTitle[iLevel] = sTitle;
        vTitle.length = iLevel + 1;   // 深度优先，回到浅层时截断更深层

        // folder 字段：从数据库根的直接子节点开始，不含数据库根
        var sFolder = (iLevel >= 1) ? vTitle.slice(1, iLevel + 1).join(' > ') : '';
        var sParent = (iLevel >= 2) ? vTitle.slice(1, iLevel).join(' > ') : '';

        if(iLevel >= 1){
            if(!mapChildren[sParent]) mapChildren[sParent] = [];
            mapChildren[sParent].push(sTitle);
        }

        var sPref = xNyf.detectPreferredFile(sSsgPath, 'html;qrich;txt;md;rtf>htm;ini;log');
        var bFolder = xNyf.folderExists(sSsgPath, false);

        listNodes.push({
            ssg: sSsgPath,
            title: sTitle,
            level: iLevel,
            folder: sFolder,
            hasContent: !!sPref,
            isFolder: bFolder
        });
    });

    // ---------- 工具函数 ----------
    // 逐级创建目录，返回最终目录路径
    var _make_dir = function(sBase, aParts){
        var xDir = new CLocalDir(sBase);
        for(var i = 0; i < aParts.length; i++){
            var nm = _validate_name(aParts[i]);
            var xNext = new CLocalDir(xDir.toString());
            xNext.append(nm);
            if(!xNext.exists()){
                xDir.createDirectory(nm);
            }
            xDir = xNext;
        }
        return xDir.toString();
    };

    // 读取节点内容（原始文本，不转换）
    var _read_content = function(sSsgPath){
        var sPref = xNyf.detectPreferredFile(sSsgPath, 'html;qrich;txt;md;rtf>htm;ini;log');
        if(!sPref) return '';
        var xFn = new CLocalFile(sSsgPath);
        xFn.append(sPref);
        var s = xNyf.loadText(xFn, 'auto');
        return (s == null) ? '' : s;
    };

    // 生成 frontmatter
    var _build_frontmatter = function(sTitle, sFolder){
        var s = '';
        s += '---\n';
        s += 'title: "' + sTitle + '"\n';
        s += 'source: ' + CONFIG.source + '\n';
        s += 'database: "' + sDbName + '"\n';
        s += 'folder: "' + sFolder + '"\n';
        s += '---\n';
        return s;
    };

    // ---------- 第二遍：写文件 ----------
    plugin.initProgressRange(plugin.getScriptTitle(), listNodes.length);

    var nIndex = 0, nNotes = 0;

    for(var k = 0; k < listNodes.length; k++){
        var nd = listNodes[k];

        var bContinue = plugin.ctrlProgressBar(nd.title, 1, true);
        if(!bContinue) break;

        if(nd.level < 1) continue;   // 跳过数据库根本身

        // 磁盘相对路径：folder 各层标题转目录名
        var parts = nd.folder.split(' > ');
        var sDir = _make_dir(sDstDir, [sTopDir].concat(parts));

        // 有内容 -> 写 index.md
        if(nd.hasContent){
            var sContent = _read_content(nd.ssg);
            var sBody = _build_frontmatter(nd.title, nd.folder);
            sBody += '# ' + nd.title + '\n\n';
            sBody += sContent;
            var xFn = new CLocalFile(sDir);
            xFn.append('index.md');
            if(xFn.saveUtf8(sBody) > 0) nNotes++;
        }

        // 有子项 -> 写 _index.md（分类索引）
        var vKids = mapChildren[nd.folder];
        if(vKids && vKids.length){
            var sIdx = '# ' + nd.title + '\n\n';
            for(var m = 0; m < vKids.length; m++){
                sIdx += '- [[' + vKids[m] + ']]\n';
            }
            var xFn2 = new CLocalFile(sDir);
            xFn2.append('_index.md');
            if(xFn2.saveUtf8(sIdx) > 0) nIndex++;
        }
    }

    alert('导出完成。\n笔记：' + nNotes + '\n分类索引：' + nIndex + '\n\n输出目录：' + sDstDir
        + '\n\n下一步：python mybase2obsidian.py "' + sDstDir + '" <Vault目录>');

}catch(e){
    if(e !== 'cancel') alert(e);
}
