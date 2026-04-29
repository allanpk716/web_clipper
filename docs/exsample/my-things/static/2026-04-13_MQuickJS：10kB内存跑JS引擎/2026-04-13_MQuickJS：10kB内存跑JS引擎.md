# 10kB 内存跑 JS 引擎？V8 的千分之一大小，这位传奇程序员又出手了

> 公众号: 何三笔记
> 发布时间: 2026-04-12 13:10
> 原文链接: https://mp.weixin.qq.com/s/3so0SsVVttwHRiRL1NAwYQ

---


大家好，我是何三，独立开发者

![mquickjs](images/img_001.png)mquickjs

曾在 Hacker News 首页被一个项目刷屏了——1500+ upvote，569 条评论，讨论热度快赶上 AI 新框架发布了。

主角不是什么大厂的重量级产品，是一个用纯 C 写的 JavaScript 引擎，核心代码文件不到 20 个，总共才 45 个 commit。

**10kB RAM 就能跑 JS 代码。整个引擎加 C 库才 100kB ROM。**

Chrome 用的 V8 引擎要吃掉大约 100MB 内存。Bellard 自己之前写的 QuickJS，算是已经很轻量了，也要 ~200KB。

MQuickJS 比 V8 小了一万倍。

一万倍。我打了这几个字又删了三遍，确认没写错。

![mquickjs](images/img_002.png)mquickjs

项目叫 **MicroQuickJS**，作者 Fabrice Bellard。

这名字听着陌生？没关系。**FFmpeg** 你肯定知道——全球最流行的多媒体处理框架，几乎所有视频网站底层都在用它。**QEMU** 也是他写的——云服务商跑虚拟机的标配。还有 QuickJS 本身，已经够轻量了，他嫌还不够小，于是又撸了一个 MQuickJS。

法国人，一个人写。程序员圈里管他叫"上帝之手"。

我有时候在想，这老哥是不是有什么特殊的降维打击能力——别人做一个项目要团队几十人迭代好几年，他一个人在巴黎的公寓里，隔两年就扔出来一个重新定义行业标准的东西。这已经不是"厉害"能形容的了，怎么说呢，就是那种——你玩游戏碰到开了全图挂的大佬，你只能观战。

## 怎么把 200KB 塞进 10KB 里

Bellard 的思路说白了就一句话：**能不用的全砍，能换的全换，能用 1 bit 解决的绝不用 2 bit。**

**内存分配**：C 标准库的 malloc 和 free？不要了。MQuickJS 自带一套内存分配器，你只需要给它一块 buffer：

```
uint8_t mem_buf[8192];  // 8KB，够了
JSContext *ctx = JS_NewContext(mem_buf, sizeof(mem_buf), &js_stdlib);
```

引擎只在你给的这块 buffer 里活动，绝不越界。buffer 满了，GC 自动回收。这设计其实有点像给引擎租了个小公寓——你爱怎么折腾都行，但别出门。

**垃圾回收**：QuickJS 用的是引用计数（reference counting），问题是用久了内存碎片一堆，跟硬盘用久了要碎片整理一个道理。MQuickJS 换成了追踪式压缩 GC（tracing + compacting），对象可以搬家，内存整整齐齐挤在一起，一点缝都不留。

这个压缩 GC 的实现细节说实话我也没完全搞懂，源码看了一半就放弃了——有兴趣的可以去翻 `gc.c`，有懂的大佬欢迎指正。

**标准库**：QuickJS 运行时要创建一堆内置对象（Object、Array、Function 之类的），每一个都要占 RAM。MQuickJS 把整个标准库在编译时就转成 C 结构体写进了 ROM。运行时？运行时几乎不用额外 RAM。等于把家具全焊死在墙上了，省了搬家的空间。

**字符串编码**：JavaScript 标准规定字符串底层是 UTF-16，每个字符最少占 2 字节。但现实是大部分 JS 代码写的都是英文和 ASCII，每个字符其实 1 字节就够了。MQuickJS 用了 WTF-8 编码（对，就叫这个名），英文 1 字节，中文 3 字节，动态自适应。光这一改，字符串的内存占用就砍了一大半。

**解析器**：QuickJS 的解析器是递归的，遇到深度嵌套的代码可能会把 C 栈撑爆。在内存只有几十 kB 的环境里，这可是致命的。MQuickJS 的解析器刻意避免了递归，栈深度有严格上界。

![mquickjs](images/img_003.png)mquickjs

每一个改动单看都不算什么，但全堆在一起——效果就是**把 200KB 的引擎塞进了 10KB 的 RAM 里**。

这种工程能力，怎么说呢，服了。

## 代价是什么

天下没有免费的压缩。MQuickJS 只支持 ES5 的一个子集，还强制开了严格模式。一些 JS 的"坏习惯"直接不让用：

- 数组不能有空洞。`a[0] = 1; a[10] = 2;` 直接报错
- 不支持 `const` 和 `let`，只能用 `var`
- Date 对象只有 `Date.now()`，完整的日期操作？没有
- 不支持 `new Number(1)` 这类值装箱
- 正则只有 ASCII 的大小写折叠

HN 上有人吐槽："Date 只支持 Date.now()，这在实际项目里会炸的。"

也会有人问"能不能跑 TypeScript？"

不能。也不应该。

MQuickJS 不是给你跑 npm 包的。它的战场是 STM32、ESP32 这些 RAM 只有几十 KB 的微控制器。在这种设备上，你写的是控制传感器、读写 GPIO、处理简单协议的嵌入式脚本。你指望在上面跑 React？想什么呢。

不过 Simonw（Datasette 的作者）想了一个很妙的场景：在服务端跑用户提交的自定义 JS 脚本。用户写的代码可能很蠢甚至恶意，但 MQuickJS 自带的内存限制就是天然沙箱——你给了它 10KB，它就算想作恶也翻不出这个 buffer。他甚至让 Claude Code 花了 15 个小时把 MQuickJS 移植到了纯 Python，402 个测试只失败了 2 个。

## 跑一下试试

官方给了一个很能打的 demo：用 10kB 内存限制跑 Mandelbrot 分形图。

```
# 克隆仓库
git clone https://github.com/bellard/mquickjs.git
cd mquickjs
make

# 用 10kB 内存限制跑 Mandelbrot 测试
./mqjs --memory-limit 10k tests/mandelbrot.js
```

就这一条命令。Mandelbrot 分形在你终端里被计算出来，而整个 JS 引擎只吃了 **10kB** 内存。

还有字节码模式——把 JS 编译成字节码，直接烧进芯片 ROM 里运行：

```
# 编译为字节码
./mqjs -o mandelbrot.bin tests/mandelbrot.js

# 运行预编译字节码
./mqjs -b mandelbrot.bin
```

连编译阶段的开销都省了。这玩意儿真的是为嵌入式而生的。

## 会改变什么？

坦白说，MQuickJS 不会影响你写 React、用 Vite、在 Chrome 里调试代码的日常。该干嘛干嘛。

但它打开了一扇门——**JavaScript 不再只是浏览器的语言，也不只是 Node.js 的语言，它可以跑在一颗 2 美元的微控制器上。**

以前想在嵌入式设备上跑脚本，你的选择基本是 Lua 或 MicroPython。Lua 是不错，但生态毕竟小。MicroPython 嘛……性能堪忧。JavaScript 作为全球使用人数最多的编程语言，终于有一个能塞进芯片的引擎了。这对 IoT 开发者、硬件工程师、创客社区来说，真的是一个挺大的事。

HN 上已经有人把它移植到了 ESP32 上，用的还是 Claude Code 辅助移植——这条路跑通了。

一句话总结：**MQuickJS 证明了 JavaScript 可以小到塞进 10kB 的内存里**。有各种限制不假，但把一门现代编程语言压缩到极致、跑在最卑微的硬件上——这种工程美学，真不是每天都能碰到的。

*本文使用 MGO 编辑并发布*

> 关注"何三笔记"，回复"mgo" 免费下载使用

