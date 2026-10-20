# genie 方言参考 —— 配置语言语义

> 本页是 **genie 方言**的权威语义文档：每个调用的功能、输入、单位、
> 约束、默认值与陷阱。方言有三位一体的实现——本地 `fdtd` 包（GPU 直跑）、
> 线格式 SimConfig JSON（HTTP 提交体）、云端 SDK `genie`（pip 包）——
> 三者方法名逐一同名，语义以本页为准。机器可读契约见
> `/docs`（OpenAPI）；本页是全量语义层，签名与默认值已并入各方法条目。
>
> 标注约定：**【方言】**=三方一致可用；**【本地专属】**=仅在本地 `fdtd`
> 包可用、尚未进入线格式（云端提交会 422，属路线图"schema 扩展"）；
> **【服务端】**=只在云端语义存在。

**总则**

- 单位一律 SI：长度米、时间秒、频率赫兹、角频率弧度/秒、角度度。
- 配置对象全部链式构造：`f.mat.add_const().name('si').eps(2.1)`，
  顺序无关（少数覆盖语义除外，见 `from_face`）。
- 线格式里的 `type` 判别字段由 `add_*` 工厂方法隐式决定，无需手写
  （`add_box()` 即 `"type": "box"`）。
- 服务器对未知字段一律 422 拒绝（拼错字段名会大声报错，不会静默忽略）。
- 错误分两层：形状/取值错 → 422（逐字段定位）；"合法但巨大" →
  400 资源守卫拒绝。

---

## 增量修改 —— 改一处，不重写整份模型

Studio 里有一份**活着的模型**（会话的 `f`）。改它有四条路，按"代价最小"
选，不要一律用最重的那条：

| 你要做的 | 用什么 | 服务端代价 |
|---|---|---|
| 改一个值 | `patch` 一条 `set` | 只解析这一条 |
| 加 / 删一个对象 | `patch` 的 `append` / `remove` | 只动这一个 |
| 换掉整份模型 | `replace` | 全量解析 + 全量校验 |
| 循环 / 扫参 / 程序化建模 | `exec`（`mode=build`） | 事务：全对或全错 |

### 一条 op 的形状

```json
{"path": "mesh.dx", "value": 2e-8}
{"verb": "append", "path": "monitor", "value": {"type": "time", "name": "t1", "field": "Ey"}}
{"verb": "remove", "path": "monitor.0"}
```

- `verb` 只有三个：`set`（缺省）/ `append`（数组尾加一个）/ `remove`（删数组一个）。
- 路径是**点分**的，数组下标就是一个路径段：`geometry.2.priority`。
- 数组那一段**可以是下标，也可以是名字**（对象的 `name`）：`geometry.grating.priority`
  与 `geometry.2.priority` 等价；`{"verb":"remove","path":"geometry.grating"}` 删的
  就是叫 grating 的那个。**改/删优先用名字**——按下标是"读→算→写"，别人刚插了
  一个，你动到的就是别人。名字写错会报错并把该数组里有的名字列出来。
- `append` 的 path 指**数组**，回报的路径是 `monitor.1`（新元素的下标）。
  有它在，"加一个源"不用先把整张表读下来。
- `remove` 的 path 指**元素**；删中间的，后面下标自动前移。
- **一批 op 全对或全错**：有一条不成立，整批不提交，模型一个字节不动，
  报错里点名是第几条、哪个路径、为什么。
- `set` 会创建缺失的中间节点（`mesh.dy` 不存在也能设）；`append` / `remove`
  只认**已经存在**的数组——不猜你要建什么。

### 落地与拒绝的回声

改完服务端会回流一次快照：

- `origin=patch` + `paths`（实际变动的路径，如上例的 `monitor.1`）——界面
  据此只刷新那几处，不重建面板；
- `origin=reject`——这批被拒了，模型没动。界面会把本地那份**改回**服务端的值。

### 不要"读整份 → 改 → 写回"

这是最容易犯的写法，代价有三个：

1. 你得先拿到全量模型（多一次往返，而且它可能在这期间被别人改了）；
2. 任何一处写错，整份模型一起坏掉——而你想改的只是一个字段；
3. 两个客户端各读一份、各写回，后写的把先写的盖掉（丢改动）。

`append` / `remove` 就是为了让第 3 条不成立：加一个就是加一个。

### 几件常做的事

```json
// 加一个材料（名字自己定，结构里按名字引用）
{"verb": "append", "path": "materials", "value": {"type": "const", "name": "si", "eps": 12.1}}

// 加一个监视器（time/freq/index 三类各自不许重名）
{"verb": "append", "path": "monitor", "value": {"type": "freq", "name": "r", "field": "Ey", "freq": {"center": 2e14, "bw": 1e14, "n": 101}}}

// 删掉叫 grating 的那个结构（也可以写下标 geometry.2，但名字更稳）
{"verb": "remove", "path": "geometry.grating"}

// 改网格步长
{"path": "mesh.dx", "value": 5e-8}
```

整份模型（`SimConfig`）的字段与约束见本页各节；提交体校验失败一律 422
并逐字段定位。

---

## Domain —— 物理域与边界

配置对象：`f.domain`（本地 `Domain()`，方言 `domain` 节）。

### `f.domain.x_range = (lo, hi)`（y/z 同）【方言】
- 功能：设定各轴物理范围。
- 单位：米。约束：`hi > lo` 且有限（两方同守卫）。
- 默认：必填。本地构造缺省 `(-0.5µm, 0.5µm)`（z 为 ±1µm），方言必填。
- 语义注：域范围边缘即 PML 内缘（PML 向外延伸，不占用户域）。

### `f.domain.total_time = 6e-14`【方言】
- 功能：总物理时长（决定 dt 与监视器积分窗规划）。
- 单位：秒。约束：必须 > 0（本地在装配期校验，方言在 422 层）。
- 默认：必填。
- 陷阱：作业推进到 `total_time` 对应的网格时间容量为止（步数是 build 后
  派生量，不在提交时设置），freq 监视器的 DFT/切趾窗按 total_time 规划
  ——想跑长请把 total_time 设够。

### `f.domain.cfl = 0.9`【方言】
- 功能：CFL 系数（dt 缩放）。约束：`0 < cfl <= 1`。默认 `0.9`。

### `f.domain.boundary_condition(face, kind, **kw)`【方言】
- 功能：设定某面边界（线格式字段：`boundary`，六面字典）。
  `face ∈ {x_min…z_max}`；`kind ∈ {pec, pmc, periodic, pml, bloch}`。
- 未设置的面默认 **pec**（不是 pml——横向周期/布洛赫场景务必显式设）。
- 各 kind 的参数与约束：
  - `pml`：`layers`（默认 12，**>= 2**）、`kappa_max`（默认 1.0，
    **>= 1**）、`order`（默认 3，**>= 1** 且整数值）。
  - `bloch`：`k=(kx, ky, kz)`（三分量须有限）或 `from_source=True`
    （从主平面波源取 k）。二者同传时 **from_source=True 无条件优先，
显式 k 被静默忽略**——显式 k 需 from_source 缺省/False（2026-09-07
用户裁决 A1=甲，随实现口径，内核 docstring 同步）；`n_background` > 0
    （默认 1.0）。
  - `pec/pmc/periodic`：无参数。
- 硬约束：periodic/bloch 必须同轴成对（`x_min`+`x_max` 都设才行）；
  from_source 需要存在主 TFSF 源。
- 陷阱：斜入射配 bloch 时 k 用**波矢**（rad/m，非方向余弦）。

---

## Mesh —— 网格

配置对象：`f.mesh`。

### `f.mesh.dx = 20e-9`【方言】
- 功能：名义格距。单位：米。约束：> 0。必填。

### `f.mesh.dy / f.mesh.dz`【方言】
- 功能：各轴独立格距。**未设置时静默回退 dx**（各向同性）。
- 方言注意：线格式中 dy/dz 缺省即回退；显式设置等于 dx 时
  语义相同但配置不同（省略它们是安全的）。

### `f.mesh.refine(x_range, y_range, z_range, factor=, growth_rate=)`【方言】
- 功能：长方体加密区。factor 为 int 或 `(fx, fy, fz)`，均 **>= 2**；
  growth_rate >= 1.0（默认 1.2）。撤销全部加密区用
  `clear_refinements()`。
- 【本地专属】逐轴独立形态 `refine(..., fx=2, fy=4, fz=2)`（方言
  用 factor 三元列表表达同一能力）。
- 约束：各区间 `lo < hi`；全域外区间被拒；部分越域合法（逐轴裁剪）。
- **重要陷阱：名义 factor ≠ 实际最细格**。渐变过渡带经保形归一化后
  实际最细格可比 dx/factor 更细（f2/g1.2 实测 ~2.68×，f8/g1.2 达
  ~26×）；dt 与加密上限守卫都按**实际**最细格计算。growth_rate=1.0
  （无过渡带）时精确等于名义值。
- `max_refinement`（默认 128，>= 1）/ `min_cells`（默认 10，>= 1）：
  细化上限与每轴最少格数（2026-09 方言开放；SDK `f.mesh.max_refinement`
  属性赋值，默认值可不写）。

---

## Materials —— 材料

配置对象：`f.mat`。三种构造入口 + 查询族。

### `f.mat.add_const().name('sio2').eps(2.10).mu(1.0)`【方言】
- `name`：必填（装配期校验，重名后写覆盖先写）。
- `eps` / `mu`：**相对**介电/磁常数（用户传 n²，不是折射率！），
  默认 1.0；约束：有限且 > 0。eps=mu=1 即真空。
- `color`（可选，`const` / `lorentz` 均支持）：**显示用**材料色，
  `'#RRGGBB'` 或 `'RRGGBB'`（归一为 `#RRGGBB` 大写）。GUI 的 3D 视图
  按材料上色——同一材料的实体共享一色；缺省时前端按材料名稳定散列取
  调色板（同名同色、跨会话稳定）。**求解器不消费该字段**，纯表现层，
  不进 translate。取值非法 → 422。
- 查询【方言】：`list_models()` / `has_model(n)` / `count_models` /
  `remove_model(n)` / `clear_models()`（本地与 SDK 同名同行为）。

### `f.mat.add_lorentz().name('ag').eps_inf(2.0).mu_inf(1.0)...`【方言】
- `eps_inf` / `mu_inf`：高频极限相对常数，> 0 有限，默认 1.0
  （> 0 守卫在 api/方言层；内核 L1 接受任意有限值）。
- 极点追加——落入线格式的 `poles` / `mu_poles` 两个列表；**每 pole
  两形态（值即形态）**：
  - **iso 各向同性**：`add_eps_lorentz_pole(omega_0, gamma, delta_eps=1.0)`
    ——参数全标量、无 alpha/beta → 内核自动三轴展开（任意偏振有色散）；
    ω₀、γ 单位 **rad/s**；ω₀ > 0（ω₀=0 属 Drude 入口，422）；delta_eps
    无量纲默认 1.0。Drude：`add_eps_drude_pole(omega_p, gamma)`（ωp>0）。
  - **rank-1**：同参数标量 + `alpha=[x,y,z]`（必）± `beta=[...]`（缺省
    =alpha）→ 单根 `VectorPole(α,β)`：驱动沿 α 的色散，D 耦合 β（lorentz
    ωp²=Δε·ω₀²、drude ωp²=ω_p²）。守卫：只有 beta 无 alpha → 422；两向量
    逐元有限、norm>0、**自动归一**。α=β=非主轴 → 倾斜单轴（自动产生非
    对角分量）；α≠β 为非对称耦合（引擎按 α·F / β·P 原样消费，互易介质
    请用 α=β）。
  - 磁侧镜像：`add_mu_lorentz_pole(...)` / `add_mu_drude_pole(...)`。
- **增益语义（M2 定案，2026-09-07）**：增益通道 = **ωp²<0**（负振子
  强度/负 Δε——临界点模型中增益的标准表达），接受且**有界稳定**：ADE
  递推根只依赖 (ω₀,γ)，ωp² 只进驱动项。**γ<0（负阻尼）不是增益通道**，
  被内核 L1 `ade_coeffs` 硬拒（无饱和机制的时域增益必发散；不在 schema
  422 层拦，作业在内核 build 期报错）。
- ⚠ **3 元极点速记已移除（breaking，内核 1.4.0）**：ω₀/ω_p/γ/Δε 只收
  标量。需要逐轴独立参数 → 叠多个 iso/rank-1 pole；存量 3 元配置的
  迁移入口在 UI（「拆成三个各向同性 pole」）。
- 张量形态（2026-09 全开）：`eps/mu/eps_inf/mu_inf` 接受 标量（iso）
  | 3 元 `[xx,yy,zz]`（对角）| **3×3 嵌套数组**（完整张量，行优先，
  可含非对角）。**值即形态**——不存模式字段，JSON 形状即表达。
  守卫：逐元有限、**主对角 > 0**（非对角允许负为 L1 定案；主对角 > 0
  守卫在 api/方言层，L1 接受任意有限值）、
  **对称**（互易介质：|e_ij − e_ji| 相对容差 1e-6，超限 422「张量须
  对称」）、形状须 3×3。UI 输上三角自动镜像下三角（同屏回显）。
- 极点：ω₀/ω_p/γ/Δε 只收标量（iso），rank-1 加 alpha/beta（见上）；
  增益=负 Δε（ωp²<0）通道接受（见上 M2 定案）；γ<0 负阻尼被内核 L1 硬拒
  （schema 层不拦，作业 build 期报错）。

### `f.mat.add_from_library('Au', name='au', fit_range=(lo,hi), n_drude=1, n_lorentz=2, maxfev=5000)`【方言】
- 功能：从 n-k 材质库生成色散材料——**客户端展开糖**（F1 2026-09
  定案：fit 全归服务仓，内核 pole-only）。SDK 内部立即
  `genie.material.load_library_nk`（优先 SDK 自带本地库
  `genie/nkdata/`，37 种，离线可用；preview 经本地端点执行，
  材料库与 scipy 随 SDK 在服务端环境可用，2026-10 起 Pyodide 镜像已退役）→ `fit_nk` → 注册 **lorentz
  pole 材料节点**（eps_inf + poles）——**配置里携带的就是 pole**，
  本地/云端同构；拟合即时发生（无延迟链式 setter，fit 参数走
  关键字实参）。
- 数值连续性：与旧内核服务端拟合一致（golden 锁
  `sdk/tests/test_fit_golden.py`，rel=1e-9）。
- `library`：库名（如 `'Au'`）；`genie.material.list_library_materials()`
  列全部（云端 `GET /api/tools/nk_library` 同一份随迁库兜底——
  G19b 起网关层真实现，`X-API-Key` 鉴权）。
- `fit_range`：波长区间（米），默认 (400nm, 800nm)；`n_drude`
  （默认 0）/ `n_lorentz`（默认 2）：极点数；`maxfev`（默认 5000）。
- 依赖：拟合需要 scipy——缺失时 `ImportError` 指路
  `pip install scipy`，不静默降级。
- 裸 `from_library` 线格式节点（手写配置/MCP）：**已拒收 + 迁移指引**
  （F2 落地，2026-09）。内核 serve schema（`LibraryMatSpec`）对
  `type: "from_library"` 节点抛明确 `ValueError`（校验期
  model_validate/parse_config 与作业期 translate 同一手），消息指路：
  ① 网关 `POST /api/tools/material_fit` 端点（G19b 网关层直实现，
  `X-API-Key` 鉴权；并发上限 2，满载 503）拟合后以 lorentz pole
  节点提交；② SDK `add_from_library` 糖（同一流程自动完成）；
  ③ 直接提交 `type: "lorentz"` pole 参数。类保留在线格式 union 中
  正是为了让 discriminator 命中后吃到该指路错误（而非 pydantic 泛化
  报错）；MCP 内嵌 schema 已按 F2 内核再生成。原节点字段
  （library/fit_range/n_drude/n_lorentz/maxfev/quiet——quiet 服务侧
  已无打印面，恒视为 True）随拒收一并失去消费方。
- 【自带数据】`genie.material.fit_nk((wl, n, k), ...)` 直接出
  `material_node` 可粘回配置；服务端 `POST /api/tools/material_fit`
  给 `nk` 三列同样返回 `material_node`（SDK/agent 车道）。UI 拟合
  面板两种模式（库材料卡内联 / 独立面板）与 preview 同走本地端点
  （同一 `fit_nk` 实现；2026-10 起 Pyodide 退役，拟合在本地 Python 端）。

---

## Geometry —— 结构

配置对象：`f.geom`。八种形状全开（2026-09 内核 serve 1.1.0 起；
此前五种）。

**通用可选字段 `name`**（八种形状都支持）：几何对象的显示名，供 GUI 左树与
3D 标签显示（`f.geom.add_box()...name('mwj')`）。与材料 `color` 同性质——
纯表现层，求解器不消费；缺省时前端回退到类型名（"Box" / "N-gon"）。
不在装配期占用唯一性（**同名不报错**，重名会得到两行同名）。

### `f.geom.add_box().material('sio2').x_range(lo,hi).y_range(lo,hi).z_range(lo,hi).priority(1)`【方言】
- `material`：引用材料名（**必须已在 f.mat 定义**，装配期校验）。
- 各 range：`hi > lo`。`priority`：整数默认 0（重叠区域高优先者胜）。

### `f.geom.add_sphere().material('m').center(x,y,z).radius(r).priority(n)`【方言】
- center 默认 (0,0,0)；radius > 0 必填（米）。

### `f.geom.add_cylinder().material('m').center(...).radius(r).height(h).priority(n)`【方言】
- radius > 0、height > 0 必填（米）。

### `f.geom.add_ngon_z().material('m').center(...).n_sides(n).circumradius(r).height(h).priority(n)`【方言】
- 功能：正 n 边形（z 轴挤出）——孔阵/柱阵的主力形状。
- `n_sides`：整数 **>= 3**（n=2 会使结构退化消失）；`circumradius`、
  `height` > 0（米）。center 默认 (0,0,0)。

### `f.geom.add_polygon_z().material('m').vertices([(x, y), ...]).z_range(lo,hi).priority(n)`【方言】
- 功能：任意多边形（z 轴挤出）——超表面单元形状。
- `vertices`：(x, y) 对列表，至少 3 点，坐标有限（米）。
  **子多边形分隔哨兵**：JSON 提交用 `[null, null]` 对（JSON 严格语法
  无 NaN）；Python 侧 `(float('nan'), float('nan'))` 与 `(None, None)`
  均可——三种入态归一为内核的 (nan, nan) 哨兵，每个子多边形须 >=3
  顶点（内核装配期校验）。
- `z_range`：`hi > lo` 必填。

### `f.geom.add_ellipse_z().material('m').center(...).rx(rx).ry(ry).height(h).priority(n)`【方言】
- 功能：椭圆（z 轴挤出）——椭圆孔/椭圆波导（2026-09 开放）。
- `rx`、`ry`、`height` > 0 必填（米）；center 默认 (0,0,0)。

### `f.geom.add_ring_z().material('m').center(...).inner_radius(ri).outer_radius(ro).height(h).priority(n)`【方言】
- 功能：圆环（z 轴挤出）——环缝谐振器主力形状（2026-09 开放）。
- `inner_radius` >= 0（**0 = 实心盘**）；`outer_radius` > 0 且
  `inner < outer`（schema 期拒）；`height` > 0（米）。

### `f.geom.add_polygon_swept().material('m').vertices([...]).z_range(lo,hi).tilt(dx_dz,dy_dz).priority(n)`【方言】
- 功能：带斜切（shear）的 z 轴挤出多边形——斜纹超表面/倾斜光栅
  （2026-09 开放）。
- `vertices`/`z_range` 语义同 `polygon_z`（哨兵对同一手）。
- `tilt(dx_dz, dy_dz)`：截面随 (z − z_center) 平移的斜率，可省略
  （=不斜切）；每分量有限且 |v| <= 1000（大倾角会把截面推出域外，
  schema 期拒）。本地 `tilt_deg(θx, θy)`（度）是便捷换算，不进线格式。

- `clear()`【方言】：清空全部结构。
- 语义注：结构整体越出物理域只**警告**不拒绝（可能是有意的局部结构）。

---

## Source —— 源

配置对象：`f.src`。三入口；前四个时域参数三入口共享。

### 共享时序参数【方言】
- `freq(f)`：载波，Hz，**> 0** 必填。
- `bandwidth(bw)`：Hz，**> 0** 必填（准 CW 用小正带宽，0 被拒）。
  **口径声明**（2026-09-07 内核 L2 审查批 β，行为不变）：`bw` 是高斯
  **调制参数**而非 FWHM 本身——内核取 σ = 0.5/bw（包络振幅标准差，
  历史约定，行为被测试逐位钉住）。实际宽度：时域振幅 FWHM ≈
  1.18/bw，时域强度 FWHM ≈ 0.83/bw，谱强度 FWHM ≈ 0.53·bw。
- `delay(d)`：秒，默认 0；**负值合法**（"早脉冲"用法）。
- `phase(p)`：弧度，默认 0。
- `name(n)`：可选；**未命名的源被能量诊断跳过**——建议总命名。

### `f.src.add_soft_source()`【方言】
- `center(x,y,z)` 米（必填）；`size(sx,sy,sz)` 米（每槽 <=0 = 该轴
  单格；不调用 = 点源）；`polarization(px,py,pz)` 复数分量，默认
  (1,0,0)=Ex（方言线格式 `[re, im]×3` 对，虚部表达圆/椭圆偏振）；
- `amplitude(a)` 默认 1.0；`kind('electric'|'magnetic')` 默认前者。

### `f.src.add_plane_wave()`（均匀平面波 TF/SF）【方言】
- `direction('+'|'-')` 默认 '+'；`amplitude` 默认 1.0。
- `center(x,y,z)`：注入面横轴中心，默认域心。
- `theta/phi/psi`（度）：theta ∈ [0,180] 闭区间；phi/psi ∈ [0,360)
  半开。**默认 (0,0,0) = 沿 +z 传播、电场沿 Ey**（不是 Ex！时域
  监视器 field('Ex') 会读到 0）。
- `size(sx, sy, sz)`：全局三槽；每槽 <=0/None = 非传播轴，传播轴 =
  恰一非正槽（歧义时默认 z）。两参调用 `size(sx, sy)` 等价
  `size(sx, sy, 0)`。
- `propagation_axis('x'|'y'|'z')`：显式选轴（与 size 正槽冲突会 422）；
  全横截面 span 必须用它。
- `from_face('z_min'|…)`：一键贴面注入——自动钉传播轴/方向/注入面
  （该面内侧 2.5 格 = PML 内缘）/横轴中心=域中点，**覆盖此前设置的
  center 与 propagation_axis/direction**；size 与角度仍可组合。
- ⚠ **窗口设计陷阱（非归一化缺陷，2026-09-07 口径更正）**：
  from_face 注入面贴 PML 内缘，脉冲到达远端监视器晚 ~d/c——freq
  监视器的 apodize stop 窗若仍按"注入在域心"设定，3σ 尾巴撞进窗的
  余弦下降沿，DFT 通量被静默砍掉（曾实测真空 T≈0.14；注入场本身
  逐位无损）。设窗公式与 build 期灰区告警判据见内核仓 docs/GUIDE.md 陷阱节
  from_face 段（修复档案段二.44）：stop ≥ t0 + d_max/cosθ + 3σ +
  width/2。按此设窗即可用 from_face 做定量透过率。

### `f.src.add_gaussian_beam()`【方言】
- 平面波全参数 + `radius(w0)`（米，**必填**，缺省 422）：源平面孔径
  半径（3σ）；1/e² 强度束宽 ≈ 0.47·radius。

- 查询【本地专属】：`f.src.names()`（name→kind，只含命名源）。

---

## Monitor —— 监视器

配置对象：`f.mon`。三类；前四参数共享。

### 共享参数【方言】
- `name(n)`：**方言必填**（本地可匿名但不可按名检索）；**同类内
  重名被拒**，跨类同名合法。
- `center(x,y,z)` 米，默认 (0,0,0)。
- `size(sx,sy,sz)` 米：每槽 `None` = 该轴全域 span；`<= 0` = 该轴
  单格。time/freq 默认 (0,0,0) 点监视器；index 默认全 None 全域。
- `field(...)`：**方言必填**（本地默认 'all'）；time/freq 取
  {Ex,Ey,Ez,Hx,Hy,Hz,all}，index 取 {eps,mu,both}。
- 〔2026-09-15 下游注记〕**index 监视器 npz 的 eps 数组打包维序为 (z,y,x)，与坐标数组
  (x,y,z) 不一致**（下游三方事故实证：按坐标假设 reshape 会把正确结构判读成"错建"）。
  下游建议：读取用距离最近邻查询（按 (x,y,z) 目标点在展平点云取最近点，零轴序依赖）
  或先验轴序（看首两点哪个坐标在变）；详见下游坑库 pitfalls-genie.md「npz 存储与读取
  方言合集」条。

### `f.mon.add_time()`【方言】
- `down_sample(time_window=None, stride=1)`：窗（秒，正序）+ 步长
  （>= 1；非整数截断并警告）。

### `f.mon.add_freq()`【方言】
- `freq(center, bw, n)`（全 Hz；n 点数）：`bw >= 0`、
  `center - bw/2 >= 0`、`n >= 1`。
- `apodize(side=None, time_window=None, width=None)`：
  side ∈ {start, stop, both}；窗正序；width 秒 > 0。
- 陷阱：谱窗按 total_time 规划——**透过率/频谱定量场景建议显式
  apodize 到首程脉冲窗**，防 PML 回波污染（回波时序 ~ 域长/c）。

### `f.mon.add_index()`【方言】
- 介电/磁导率分布观测，装配后即可取（无需 run）。

---

## Run 与结果

### `f.run(gpu=None, timeout_s=None, poll_interval=2.0, progress=None)`【服务端】

- 提交并等待到终态。**不接受位置步数参数**（G18 起 `run.n_steps` 已删）：
  仿真时长唯一旋钮是 `domain.total_time`（SI 秒，>0 必填），作业推进到
  网格时间容量为止。`gpu`（2026-10-15 站长裁决收窄）：**卡数**（int ≥1；
  None = 缺省单卡）。设备挑选、NV 邻接链、切轴全部调度器内部自动——
  空闲显存过滤 + NV 链挑选 + 切轴接触面最小；显存不足或凑不齐 NV 链
  → 作业 FAILED（明确报错）。
- `timeout_s`：作业超时（超时 killpg）。
- `progress`：每轮询一轮回调一次（打进度条用）。
- 陷阱：`run.gpu` 不再接受设备列表/字典——用户接口只有卡数；具体卡号
  是调度器的实现细节。


### `f.get_time(name)` / `f.get_freq(name=None)` / `f.get_index(name=None)`【服务端】
- 功能：取结果（隐含 download；npz 只拉一次，按监视器缓存）。
- name 缺省取第一个该类监视器。返回纯数据对象：
  - TimeResult：`.time`、`.fields{分量:数组}`、`.x/.y/.z`
  - FreqResult：`.freqs`、`.fields{分量:复数数组}`（点监视器保持
    尾轴）；`r['Ey']` ≡ `r.fields['Ey']`
  - IndexResult：`.eps`、`.mu`、每格坐标
- **零计算定案**：结果对象不含任何派生量方法；透过率/通量读
  `f.digest()`（面/体监视器；数字服务端算好），或拿裸分量自算。

### `f.summary()`【服务端】
- 返回 `{grid_shape, dt, n_steps, monitors}` 装配元信息。

### `f.digest(job_id=None)`【服务端】
- 功能：取结果数值摘要——各监视器峰频/幅值；面监视器含透过率
  min/max/中心频值（`normalized=true` 才是物理 T；**点监视器无面积分
  不含 T**——已知方言边界）。数字服务端算好、**读取零 GPU、不拉 npz**：
  比较/调参轮次读这个，别下结果文件。
- `job_id` 缺省用本实例已提交的作业；未提交且未传 → 报错指路。
- 与 MCP 工具 `get_job_digest` 同一端点、同一读数（人类与 agent 共用）。

### `f.to_config()` / `f.to_script()`【服务端】
- 功能：导出。`to_config()` → SimConfig JSON 深拷贝（即提交体）；
  `to_script()` → 等价 genie 脚本文本（与 Studio 生成器逐字节一致，
  分享/溯源/论文用）。**重建/复制仿真的唯一公开路径 = `to_script()`
  导出脚本 + 新 `genie.connect()` 实例执行该脚本**（API 函数唯一入口
  教义）；参数批量构造走链式 API（f.domain/mat/geom/src/mon +
  `parameters()` 面）。
- `f.load_config(cfg)` 是**内部承重通道，非承诺面**：仅供会话回滚与
  表单编辑通道在 SDK 内部整替 SimConfig JSON 使用；其名字与行为均不
  对外承诺，随时可改，公开代码（用户脚本/示例）不应调用它。
  （历史注：v1 曾称 load_config 是 agent/MCP 提交轨道的基石；v2 中
  agent/MCP 走 `run_script` 的**脚本语义**——新 `genie.connect()`
  实例执行脚本提交，不再经 load_config。）
- agent/MCP 工具入参名：配置类工具（validate_config / mesh_preview /
  submit_job / run_simulation）以 `config` 传 SimConfig JSON；
  `run_script` 以 `script` 传完整 genie 脚本文本（浏览器执行，
  服务端零执行）。

### 本地专属（未进方言）
- `f.build()`（本地装配触发 GPU 编译；云端提交隐含在 run 里）、
  `f.grid()`（网格预览，需 GPU）、`f.field_arrays`、
  `f.dt/n_steps/grid_shape` 属性（云端经 summary 获取）。
- `f.source_energies()`（各源能量因子，只列命名源）：云端经 digest
  端点读取——2026-09 起 digest 恒含 `source_energies` 键（无命名源
  为空对象）。

---

## 参数与表达式（COMSOL 式全局参数，2026-10）

配置可带顶层 ``parameters`` 参数表：**{名: 数值|表达式串}**，声明序
无关（拓扑求值），供全配置的数值字段与 sweep 轴引用。

    "parameters": {"d": 1e-6, "dx": "d / 4", "f0": "3e8 / 1e-6"}

### 参数表

| 项 | 规则 |
|---|---|
| 参数名 | 标识符（字母/下划线开头，仅字母数字下划线，≤64 字符）；非法名 422 指路 |
| 参数值 | 数值，或引用**其余参数**的表达式串（环境=其余参数，声明序无关） |
| 参数环 | a 引用 b、b 引用 a → 422 带完整环链（`a→b→a`） |

### 全量数值字段接受表达式

参数表非空时，配置里**任何数值槽**（domain/mesh/材料/几何/源/监视器/
run 的数值字段，含区间元素与张量元）都可填表达式串——服务端按参数表
求值后再做结构与值守卫（**表达式原文原样上行**，求值只在服务端；
前端/SDK 预览仅为本地核对）。典型：``mesh.dx = "d/4"``——dx 随 d
联动，sweep 扫 d 时逐点重求值（见 sweep 节"从属联动"）。

### 表达式白名单（安全求值，零 eval）

| 类别 | 允许 |
|---|---|
| 常量 | 数值（int/float，含科学计数）；**字符串/布尔/None 拒收** |
| 名字 | 仅参数表查表（缺名 → 422 列可用名） |
| 二元运算 | `+ - * / % **`（`%` 取除数符号：`-7 % 3 = 2`；`**` 右结合：`2**3**2 = 512`；`-2**2 = -4`） |
| 一元运算 | `+ -` |
| 函数 | `abs(x)`、`sqrt(x)`（单参）；`min(a[, b])`、`max(a[, b])`（一或两参） |
| 单位后缀 | `primary[unit]`（绑定最紧）：`a[unit] = a × 单位尺度`，见下节「单位后缀」 |
| 其余 | **一律拒绝**——属性 `a.x`/非单位下标 `a[0]`/比较/`and·or·not`/`lambda` 等注入与三值逻辑通道全关 |

### 单位后缀（`primary[unit]`，2026-10 单位语法批）

数值与表达式槽支持**后缀单位算子**：`a[unit]` 绑定最紧（先于乘方/一元/
乘除），语义 = 纯数值换算 **`a[unit] = a × 单位尺度`**——`50[nm]` =
5e-8、`300[THz]` = 3e14、`2*50[nm]` ≡ `2×(50[nm])`。后缀可作用在
数值、参数名、括号表达式与白名单函数调用上（`sqrt(4)[um]`、`(50)[nm]`、
`x[nm]`）。

注册表 **20 单位**，按族（名 → SI 尺度）：

| 族 | 单位 |
|---|---|
| 长度 | `pm`=1e-12、`nm`=1e-9、`um`=1e-6、`µm`=1e-6、`mm`=1e-3、`cm`=1e-2、`m`=1 |
| 时间 | `fs`=1e-15、`ps`=1e-12、`ns`=1e-9、`us`=1e-6、`µs`=1e-6、`ms`=1e-3、`s`=1 |
| 频率 | `Hz`=1、`kHz`=1e3、`MHz`=1e6、`GHz`=1e9、`THz`=1e12、`PHz`=1e15 |

`µm`/`µs` 是 `um`/`us` 的 **Unicode 别名**（微米/微秒）；输入按 Unicode
NFKC 归一——无论键入 MICRO SIGN `µ`（U+00B5）还是 GREEK MU `μ`
（U+03BC）都命中同一尺度。**无维度检查（边界声明）**：单位后缀只做
数值换算，不校验量纲一致性（`1[m]+1[s]` 只数值相加、不报维度错），
量纲正确性由用户负责。

参数页 UI（Studio）三列行为：每参数卡 名称 | 值 | 单位；单位列接受
`nm` 或 `[nm]`（入库前剥括号存裸名，空 = 无量纲，datalist 提示 20 单位
按族分组、自由输入不强制下拉）。**组装规则**：值非空且单位非空 →
参数值串 = `{value}[{unit}]`；值已带 `[..]` 后缀又填单位 → 冲突红字
（二选一）。上行线格式仍为 `{名: 值串}` 零 schema 改动——服务端
parse_config 对 `{名: "50[nm]"}` 求值为 SI 数值。

### 错误语义（422 策展，kind 分档）

| kind | 含义 |
|---|---|
| `syntax` | 空表达式/语法错误/非法参数名 |
| `unknown_name` | 表达式引用了参数表外的名（消息列可用名） |
| `unknown_unit` | 后缀单位不在注册表（消息列注册表全集） |
| `illegal_node` | 白名单外节点（属性/下标/比较/布尔/未列函数…） |
| `math` | 除零/模零、sqrt 负数、溢出、结果非有限 |
| `nonatomic` | 非数值常量（字符串/布尔）、函数参数个数非法 |
| `cycle` | 参数表环（消息带 `a→b→a` 链） |
| `guard` | 表达式求值结果被字段值守卫拦下（如算出负 dx；消息带字段路径与表达式原文） |

求值错误一律 HTTP 422，消息带**配置内路径**（如 `source[0].freq 处
表达式 'f0/2' 求值失败: …`）——前端校验条与表单红点按路径定位显示。

### 代码生成规范（脚本发射与导入规范化，R2 声明式发射）

脚本方言（SDK 单一渲染器 `genie/core/script`，输出字节由 golden 测试锁）**代码即所见**——
参数块与数值槽的表达式串**原样发射**进 Python 源，不在生成期求值成
数值字面量（脚本独立可执行：参数块定义变量、字段引用变量，Python 自己
算 `d/4`）：

| 发射形态 | 规则 |
|---|---|
| 参数块·纯数值 | 字面量 + `# 原文 <JSON>`（如 `n = 3  # 原文 3`） |
| 参数块·表达式串 | 原样发射 + `# 原文 <JSON>`（如 `w = d/4  # 原文 "d/4"`） |
| 数值槽·纯数值 | 字面量（`f.mesh.dx = 2e-8`） |
| 数值槽·表达式串 | 原样发射（`f.mesh.dx = d/4`）；求值失败 → `0` 占位 + ⚠ |

**单位乘法形态**：表达式里的单位后缀 `X[unit]` 在发射时改写为乘法
`X*factor`（factor 固定科学计数：`50[nm]` → `50*1e-9`、`40[fs]` →
`40*1e-15`、`d+100[nm]` → `d+100*1e-9`），保持可执行且与求值语义等价。
`# 原文` 注释保留用户输入原串（导入器恢复通道不变）。

**导入规范化**：codeimport 把脚本里的 `<数> * <因子>` 乘法形态还原成
后缀 `<数>[<规范单位>]`，仅当因子精确匹配注册表尺度（`100*1e-9` →
`100[nm]`；含标识符的 `d+100*1e-9` → `d+100[nm]`）。因子→单位取规范首选
（长度 > 时间 > 频率：`1e-9`→`nm`、`1e-6`→`um`、`1e-3`→`mm`、`1`→`m`；
`1e-15`→`fs`、`1e3`→`kHz`…）——用户看到的是带单位的直观串。

---

## Sweep —— 参数扫描（G29b 2026-10-21：客户端编排；内核 /api/sweeps 已退役）

> **形态变更**：sweep = 普通作业的客户端组合——SDK 本地展开（轴名/
> 表达式联动/逐点校验，`SweepExpandError` 在 `f.sweep()` 调用点抛，
> 错误面与旧服务端 422 逐字同源）→ 滑动窗口提交（在途 ≤
> min(max_parallel, 配额 max_concurrent_runs)，跑一补一）→ 逐点
> digest 聚合（失败/取消点 = NaN 行；aggregate.npz 落盘形状与旧
> 服务端产物相同，下游零迁移）。子作业是普通作业：status/cancel/
> result/digest 全走既有端点。

**交付面**：Studio ✓（树「参数扫描」页）/ SDK ✓ / Agent ✓（经 `run_script` 的
SDK 面；**无独立 JSON 工具**）——三面孔都能到，但 Agent 侧走的是**脚本里的
`f.sweep(...)`**，不在 JSON 工具表里（`run_script` 的工具描述即按此引导）。

一份 base SimConfig + 一份 SweepSpec，由服务端展开为逐点配置列表。
本节只定义**线格式与展开语义**；作业调度（并行度/失败策略的执行、
NV 链选卡）见后续版本说明。线格式 JSON 形状::

    {
      "config": { ...SimConfig JSON（含 parameters 参数表）... },
      "sweep": {
        "parameters": [
          {"name": "d", "linspace": [0.5e-6, 2e-6, 4]},
          {"name": "f0", "values": [300e12, 380e12]}
        ],
        "mode": "product",
        "gpus_per_sim": 1,
        "max_parallel": 4,
        "on_failure": "continue"
      }
    }

**name 轴语义（2026-10 破坏性改版）**：轴按**参数名**寻址——``name``
必须是 base ``parameters`` 键集内的名（不在 → 422 列可用名）；旧版
``path`` 点分寻址（`mesh.dx` / `source[0].freq`）已退役，不留双系统。

**被扫参数从属联动**：展开 = 逐点深拷贝 base → 各轴
``parameters[name] = v`` → **重解析**——引用被扫参数的表达式槽逐点
联动重求值。示例：``parameters = {"d": 1e-6, "dx": "d/4"}`` 且
``mesh.dx = "dx"``，扫轴 `{"name": "d", ...}` 时每点的网格步长随 d
逐点变为 d/4——不用逐点手写各字段。

### SweepAxisSpec —— 单参数轴

| 字段 | 类型 | 约束 |
|---|---|---|
| `name` | str | **参数名**——base `parameters` 键集内（不在 → 422 列可用名）；标识符 ≤64 字符 |
| `values` | 显式列表 | 元素 number / str（枚举型，按表达式求值语义落参数槽）/ 二元数值列表（区间整体替换）；非空 |
| `linspace` | `[start, stop, n]` | 数值等差，**含两端点**；n 整数 >= 2；start != stop（单值轴请 `values: [x]`） |
| `logspace` | `[start, stop, n]` | 10^x 等比取样（即值 = 10^start … 10^stop），同 linspace 规则 |

三种取值**三选一互斥**：多给或全缺 → 422 指路错误。

### SweepSpec —— 顶层

| 字段 | 类型/默认 | 约束 |
|---|---|---|
| `parameters` | list[SweepAxisSpec] | 1..32 轴 |
| `mode` | `"product"`（默认）| 笛卡尔积；`"zip"` 要求各轴长度相等，否则 422 |
| `gpus_per_sim` | int = 1 | 1..8；>= 2 时单点仿真即多卡域分解，调度要求 NV 邻接链（同 `run.gpu` 卡数语义） |
| `max_parallel` | int = 1 | 1..16，同时运行的扫描点数上限 |
| `on_failure` | `"continue"`（默认）| `"abort"` = 任一点失败即取消余下点 |

### 展开约束表（422 期拒绝）

| 量 | 上限/规则 | 错误信息 |
|---|---|---|
| 参数轴数 | 32 | 超轴数 422 |
| 展开点数（product=各轴长度之积 / zip=公共长度） | `FDTD_MAX_SWEEP_POINTS`（默认 512，环境变量可调） | 带实际点数、各轴长度与上限 |
| zip 各轴长度 | 必须相等 | 带各轴长度列表 |
| 轴 name 在参数表内 | 必须命中 | 带轴名与可用参数名列表 |

### 展开与逐点校验语义

- 展开 = 每点深拷贝 base → 各轴 ``parameters[name]=v`` → **重解析**
  （表达式槽联动重求值 + 全量校验）：任一点非法 → 422 错误带**第几个
  点（1 基）+ 轴名 + 字段路径 + 原因**，并提示此前已有多少点合法
  （合法前缀数）。
- 示例：d 轴 linspace 4 点 × f0 轴 values 2 值（product）= 8 个配置点；
  未扫参数与其余字段逐点不动。

### SDK 用法（P2-δ）

`f.sweep(...)` 提交（`config` 缺省 = 实例当前配置），返回句柄
**不等待**——同步语义由句柄的 `wait` 提供::

    h = f.sweep(parameters=[
        {"name": "d", "linspace": [0.5e-6, 2e-6, 4]},
        {"name": "f0", "values": [300e12, 380e12]},
    ], max_parallel=4, on_failure="continue")

    h.wait(poll=2.0)            # 轮询到父终态；进度打印 progress=True
    h.download("./sweep-out")   # manifest + p0001/… 逐点 npz+summary

完整签名：
`sweep(config=None, sweep=None, *, parameters=None, gpus_per_sim=1, max_parallel=1, on_failure="continue", mode=None)`。
`parameters`（轴 dict 列表，与 SweepAxisSpec 同形——`{"name": ...}`）
与 `sweep`（完整 SweepSpec dict）二选一；`mode`（`product`/`zip`，
缺省 `product`）两种形态都可用——**便利形态也能表达 zip 扫描**；
轴名/互斥/点数上限的校验权威在服务端（422 逐条透传）。

### SweepHandle 方法表

| 方法 | 语义 |
|---|---|
| `.id` | 父作业 sweep_id |
| `.status()` | 父状态 dict 全文——父记录 + `rollup` 计数 + `points` 摘要（`GET /api/sweeps/{id}` 原样返回，不缓存）；`.state` / `.rollup` / `.points()` 都是它的取字段糖 |
| `.state` / `.rollup` | 父状态（`queued → running → done / failed / canceled`）/ 各点计数（每次访问即查） |
| `.points()` | 逐点摘要 `[{idx, state, job_id}]`（GET 父状态） |
| `.manifest()` | manifest 全文（字段清单见下「manifest 字段」） |
| `.child_id(idx, manifest=None)` | 点序号（0 基）→ 子作业 id：manifest 的 `points[idx].job_id` 优先（先知），缺席时按 `{sweep_id}-pNNNN`（1 基 4 位）推导；`.result(idx)` 内部即用它寻址（`.download(dir)` 同规则） |
| `.cancel()` | 级联取消；父已终态 → HTTP 409 透传 |
| `.wait(timeout=None, poll=2.0, progress=None)` | 轮询到父终态：`done` 返回状态 dict，`failed`/`canceled` 抛 `GenieJobError`（detail 带 rollup）；`timeout` 本地兜底，超时父仍在服务端可无参重入 |
| `.result(idx)` | 第 idx 点（0 基）子作业 npz 字节——转发 `/api/jobs/{sweep_id}-pNNNN/result`（子作业复用作业端点） |
| `.aggregate()` | **P4 聚合表** aggregate.npz 字节——转发 `GET /api/sweeps/{id}/aggregate`（未生成 404 / archived 410 透传；列名规则见下方聚合段） |
| `.download(dir)` | manifest + **aggregate.npz（best-effort，404 跳过）** + 各**成功点** npz/summary 落地 `dir/p0001/…`（失败/取消点无结果文件跳过；已存在文件跳过=可重入续传） |

**manifest 字段**（`GET /api/sweeps/{id}/manifest`，即 `.manifest()` 的返回。
UI 的 manifest 面板与 SDK 的 `child_id`/`download` 都只读下列字段——照此写
消费代码，不必去啃 app.js）：

| 字段 | 语义 |
|---|---|
| `mode` | 展开模式（`product` / `zip`，同 SweepSpec） |
| `n_points` | 展开点数（product=各轴长度之积 / zip=公共长度） |
| `p_effective` | 实际生效的并行度（`max_parallel` 是请求值，本字段是落值；UI 面板与本字段并列显示 k/P 与它） |
| `gpus_per_sim` / `max_parallel` / `on_failure` | SweepSpec 三旋钮的原样回声 |
| `axes[].name` | 轴名（参数名——`path` 寻址已退役；UI 仍带 `name ?? path` 回退，兼容 path 轴时代的旧 manifest） |
| `axes[].n_values` | 该轴取值个数（轴摘要——逐点取值不在此字段内） |
| `points[].idx` | 点序号（0 基；子作业 id 用 1 基 4 位，见下） |
| `points[].state` | 该点状态（子作业态：`queued` / `running` / `succeeded` / `failed` / `killed`；未开跑点 `state` 为 `pending`） |
| `points[].job_id` | 该点子作业 id（未开跑为 `null`——`.child_id()` 据此回退推导） |

manifest 另带逐点配置摘要（md5）与 `aggregate` 写入结果
（`{ok, file, n_result_columns, axes}` / 失败 `{ok: false, error}`，
见下方聚合段）——这两项 SDK/UI 不消费，仅供人查与非本端工具。

子作业 id 规则：`{sweep_id}-pNNNN`（点序号 1 基、4 位零填，
manifest 先知）；子点的状态/日志/摘要/预览全部走既有 `/api/jobs`
端点与 `f.jobs()` 列表。

### 结果聚合（P4，2026-09）

全点终态时服务端把逐子作业 digest.json 的数值摘要聚合为父目录
`aggregate.npz`（numpy 原生 npz，读取零新依赖），端点
`GET /api/sweeps/{id}/aggregate`（FileResponse；archived → 410
墓碑指针同款；无聚合文件 → 404 指路逐点 digest 端点）。SDK
`.aggregate()` 取字节，`.download(dir)` 会把它落为
`dir/aggregate.npz`（未生成 404 时跳过，不报错）。

列名与取值规则：

- **参数列** `param_<参数名>`：每轴一列（参数名本身是标识符，免
  合法化——`param_d`、`param_f0`）。逐点取该轴 name 在点配置
  ``parameters`` 处的值；**失败/取消点参数列保留**（参数先知）。
  列表值轴为规则 2-D 列。
- **结果列** `pt_<digest 键展平>`：子作业 digest.json 递归展平的
  **数值标量叶**（键名 `.` 连接、list 按下标，如
  `pt_monitors.0.comps.Ex.abs_max`、`pt_source_energies.s0.total`）。
  全点键**并集**；失败/取消点与缺键点该格为 **NaN**（用
  `np.array_equal(..., equal_nan=True)` 或 `np.isnan` 判缺失）。
  非数值叶（字符串/bool）不进列，键名记入 `_skipped_keys`。
- **元数据列**（0 维 JSON 字符串）：`_axes` = 列名↔参数名映射数组
  （`[{"column": "param_d", "name": "d"}, …]`）；
  `_skipped_keys` = 被跳过的非数值键并集。
- 生成时机与失败语义：与终版 manifest 同一时点写入；**best-effort**
  ——写入失败不阻父终态，manifest 的 `aggregate` 字段记
  `{ok: false, error}`（成功记 `{ok, file, n_result_columns, axes}`），
  端点相应 404。

---

## 附录 A —— 本地全集 vs 方言子集

| 能力 | 本地 fdtd | 方言（线格式/SDK） |
|---|---|---|
| geometry：box / sphere / cylinder | ✓ | ✓ |
| geometry：box / sphere / cylinder / ngon_z / polygon_z | ✓ | ✓（2026-09 方言扩展） |
| geometry：ellipse_z / ring_z / polygon_swept | ✓ | ✓（2026-09 开放，内核 serve 1.1.0 / service 0.4.0） |
| materials：const / lorentz / from_library | ✓ | ✓（from_library=SDK 客户端展开糖，配置携 pole；裸 from_library 节点 F2 已拒收+迁移指引） |
| materials：张量 eps/mu（含非对角）/ 极点 iso+rank-1(α/β) | ✓ | ✓（2026-09 完整张量+rank-1 开放；3 元极点速记已移除；from_nk 走 fit_nk/material_fit 两步等价） |
| **材料色散拟合（Drude-Lorentz fit / n-k 库 / evaluate_dispersion）** | **已移除（F2 落地，内核 pole-only：fit 面/nkdata 37 yml/顶层导出全删，裸 from_library 拒收）** | ✓ 服务/SDK 能力（F1 2026-09 随迁：SDK `genie.material.fit_nk` + 自有库 `genie/nkdata/` 37 种离线可用；backend material_fit/nk_library 端点同源实现；golden 锁算法连续性） |
| mesh：dx/dy/dz/refine | ✓ | ✓ |
| mesh：max_refinement / min_cells | ✓ | ✓（2026-09 开放） |
| source：三入口全参数 | ✓ | ✓（含 delay/phase/size/axis/from_face） |
| monitor：三类 + down_sample/apodize | ✓ | ✓ |
| 生命周期：build/run/get_* | build+run+step | run（隐含提交）/get_*（隐含下载） |
| 诊断：grid()/source_energies()/summary() | ✓ | summary() + digest 的 source_energies |
| 结果分析：`TimeResult.spectrum()`（FFT 谱）、`FreqResult.transmission()/flux()/poynting()/energy_spectrum()`（透过率/通量/坡印廷/能量谱） | ✓（本地结果对象自带） | ✗（零计算定案——读服务端 digest 或拿裸分量自算） |
| 物理常数导出：`C0_PHYS/EPS0/MU0/ETA0`（SI）与 `C0`（sim 单位归一=1） | ✓ | 经附录 D 数值使用 |

方言子集的每个字段都与本地同名同语义——**本地脚本迁移到云端只需
换 `import fdtd` → `import genie` + `FDTD()` → `connect(url,key)`**，
超集能力（上表 ✗ 项）除外。

## 附录 B —— 服务端资源守卫（400 拒绝）

| 量 | 上限 | 说明 |
|---|---|---|
| 网格总量（含 refine 增量） | 2×10⁸ cells | 可缩域/加粗网格 |
| 时长折算步数上限 | 2×10⁵ | 估算式 √3·c₀·T/(cfl·min_cell)（T = total_time） |
| 单作业 timeout_s | 14400 s | 默认 3600 |
| monitor 数量 | 16 | |
| 单监视器采样元素（样本×位置） | 5×10⁷ | 缩 size 或加 down_sample |

配置形状/取值错误 → 422（逐字段路径）；守卫拒绝 → 400；
认证问题 → 401；他人作业 → 404（不泄露存在性）。

## 附录 C —— 已知陷阱速查

1. **平面波默认偏振是 Ey**（不是 Ex）——监视器 field 要对齐。
2. **eps 是 n²**（相对介电常数），不是折射率 n。
3. **未设的面默认 pec**——横向周期/布洛赫场景务必显式设两对面。
4. **refine 名义 factor ≠ 实际最细格**（渐变带可达数倍～数十倍）。
5. **from_face 的窗口飞行时间陷阱**（注入面贴 PML 内缘 → 脉冲晚
   ~d/c 到达远端；apodize stop 窗须按 stop ≥ t0 + d_max/cosθ + 3σ +
   width/2 设定，否则 DFT 通量被静默砍掉——窗设计问题而非归一化
   缺陷，详见 `f.domain.boundary_condition` 附近 from_face 条目与
   内核仓修复档案段二.44）。
6. **点监视器没有面积分**——透过率只对面/体监视器定义。
7. **谱窗按 total_time 规划**——作业推进到 total_time 对应的网格时间
   容量为止，超窗的采样对频域结果零贡献（有告警）；定量谱学请设够
   total_time 或显式 apodize。
8. **同名覆盖/重名规则**：材料重名后写覆盖先写；同类监视器重名被拒；
   跨类同名合法。
9. **gamma < 0 是增益**（合法）；负 delay 合法（早脉冲）。
10. **结构越域只警告**——检查 3D 预览确认结构在域内。

## 附录 D —— 单位与换算

- 全接口 SI。换算常数：`C0_PHYS = 299792458 m/s`；
  波长↔频率 `f = C0_PHYS/λ`；带宽 `Δf = C0_PHYS·Δλ/λ²`。
- 特征阻抗参考 `ETA0 ≈ 376.73 Ω`（求解内部已归一）。
- 本地包另导出 `EPS0`、`MU0`（SI 真空常数）与 `C0`（**sim 单位**
  归一常数 = 1.0——与 `C0_PHYS` 同名不同义，写 SI 公式一律用后者）。

## 附录 E —— 概念面（单位 · 边界 · 生命周期 · 材料 · 网格 · 监视器 · 源）

> 本附录讲**怎么用**：选型、行为、量级与陷阱，保留库方实测数字。**字段级**
> 签名、默认值、守卫的权威在本文各节条目（§Domain / §Mesh / §Materials /
> §Source / §Monitor / §Run 与结果）；两者冲突时以各节条目为准。
> 单位一律 SI（见附录 D）。

### E.1 单位约定与换算速查

GENIE 配置只接受一套单位制——**SI**。内部换算到仿真单位由服务自动完成，
你不需要（也不应该）关心任何归一化常数。

| 量 | 你传入的单位 | 示例 |
|---|---|---|
| 长度（域范围、网格步长、束腰） | m | `20e-9`（20 nm） |
| 时间（`total_time`、`delay`、apodize 窗） | s | `60e-15`（60 fs） |
| 频率（`freq`、`bandwidth`、监视器频率窗） | Hz | `300e12`（300 THz） |
| 角频率（材料极点 ω₀/ωₚ） | **rad/s** | `2.18e15` |
| 波矢（Bloch `k`） | rad/m | `[6.28e6, 0, 0]` |

取回的结果同样回 SI：`t@名.time` 是秒，`f@名.freqs` 是赫兹。
角度 `theta/phi/psi`（平面波入射与偏振角）一律是**度**：`"theta": 30` 即 30°。

**波长 ↔ 频率**：真空换算 `f = C0 / λ`，`C0 = 299792458.0 m/s`。
常用波段速查（由上式实算，保留 7 位有效数字）：

| 波长 λ | 频率 f = C0/λ | C0/λ [THz] |
|---|---|---|
| 500 nm | 5.995849e14 Hz | 599.5849 |
| 600 nm | 4.996541e14 Hz | 499.6541 |
| 800 nm | 3.747406e14 Hz | 374.7406 |
| 1000 nm | 2.997925e14 Hz | 299.7925 |
| 1550 nm | 1.934145e14 Hz | 193.4145 |

反查（300–600 THz 常用波段）：

| 频率 f | 波长 λ = C0/f |
|---|---|
| 300 THz | 999.31 nm |
| 400 THz | 749.48 nm |
| 500 THz | 599.58 nm |
| 600 THz | 499.65 nm |

**带宽 ↔ 波长跨度**：按波长设计器件时，

    bw = C0 · Δλ / λ²

例：中心波长 λ = 1000 nm、跨度 Δλ = 100 nm 时，
bw = 299792458 × 100e-9 / (1000e-9)² ≈ **29.98 THz**。
这不是线性的：同一 Δλ 在短波长端对应更大的频率带宽，给源设 `bandwidth`
时务必在中心波长处换算。

**两个最容易踩的单位坑**：

- **极点频率是 rad/s，不是 Hz**。色散材料极点的 `omega_0`、`gamma`、
  `omega_p` 接受的是角频率 ω = 2πf。把 300 THz 直接写成 `300e12`
  会差 2π 倍——**必须乘 2π**：`"omega_0": 1.885e15`（= 2π × 300e12）。
  源的 `freq`/`bandwidth` 却是 Hz，两套并存时把量纲写进变量名
  （`f0` vs `omega0`）。
- **别把 nm/ps 原始数字直接塞进去**。服务不做单位猜测；`dx: 25` 意味着
  25 米，网格会大到被资源上限直接拒绝（HTTP 400），或量纲悄悄错掉给出
  错误物理。

### E.2 边界条件选型

`domain.boundary` 是一个「面 → 边界」的对象；每个面
（`x_min / x_max / y_min / y_max / z_min / z_max`）独立设置：

```json
"boundary": {"z_min": {"kind": "pml", "layers": 12},
              "z_max": {"kind": "pml", "layers": 12}}
```

未设置的面默认 **pec**。五种边界：

- **pec —— 理想电导体**：切向电场为零，电磁波完全反射（镜面）。适合
  腔体壁、故意要反射的金属面。做透射/散射测量时用它收尾会带来强驻波，
  一般不用。
- **pmc —— 理想磁导体**：切向磁场为零，pec 的对偶（磁壁）。主要做
  对称性剖分：结构与激励都对称时，用 pec/pmc 组合只算一半域。
  注意 **pec/pmc 不要求成对**。
- **periodic —— 周期边界**：相对两面互为镜像，出射波从对面绕回。适合
  正入射照明的周期结构（光栅、超表面单元），横向域取一个周期即可等效
  无限大横截面。**必须同轴成对设置**：`x_min` 与 `x_max` 同时 periodic
  （y、z 同理），只设一面提交时直接 422。
- **pml —— 完美匹配层**：吸收外向波、几乎无反射，是"打开的域"的标准
  选择。沿传播方向的两端各设一层，如教程中的 z 两端。参数：

  | 参数 | 默认 | 说明 |
  |---|---|---|
  | `layers` | 12 | 吸收层格数。经验值：精度优先 12–16，快速迭代 8；必须 ≥2 |
  | `kappa_max` | 1.0 | 电导率渐变峰值因子，必须 ≥1；调吸收陡峭度 |
  | `order` | 3 | 渐变多项式幂次（整数，≥1）；大 `kappa_max` 时适当加大可减反射 |

  陷阱：pml 不能与 periodic/bloch 同轴混搭（一面 pml 一面 periodic
  提交时报错，反之亦然）；把 pml 放在平面波横向会截断波前，谱里出现
  杂散反射——横向该用 periodic/bloch。
- **bloch —— 周期 + 相位扭转**：periodic 的斜入射版：绕过边界的波带上
  相位因子 e^{i·k⃗·L⃗}，使周期边界对带横向波矢的波也自洽。
  **同样必须同轴成对。**

`k` 的语义：**完整波矢** [kx, ky, kz]，单位 **rad/m**，且同一轴两面上传
**同一个向量**（每面只用自己轴向的分量做相位）。用法两选一：

```json
"boundary": {
  "x_min": {"kind": "bloch", "k": [1.63e6, 0, 6.28e6]},
  "x_max": {"kind": "bloch", "k": [1.63e6, 0, 6.28e6]},
  "z_min": {"kind": "pml", "layers": 10},
  "z_max": {"kind": "pml", "layers": 10}
}
```

（显式：k 取中心频率的波矢，横向波矢 = k0·sin(θ)；k0 = 2πf0/C0，
θ 先化弧度。）

```json
"x_min": {"kind": "bloch", "from_source": true},
"x_max": {"kind": "bloch", "from_source": true}
```

（自动：运行时从主平面波源取波矢，k = n·2πf0/c·k̂，含方向与角度。）

`from_source: true` 需要存在平面波/高斯束源，否则作业 `failed`；背景折射率
可用 `n_background` 缩放（默认 1.0）。

⚠ **优先级口径**：`from_source: true` 与显式 `k` **同传时 from_source
无条件优先、显式 `k` 被静默忽略（不报错）**——要用显式 k 就必须让
from_source 缺省/False（2026-09-07 用户裁决 A1=甲，随实现口径；权威条目
见上文 §Domain `f.domain.boundary_condition`）。
（原已删的概念页 `boundaries.md` 此处写作"显式 k 优先"，与实现相反——本次
合并按真源修正。）

**斜入射完整套路**（以源沿 z、在 x 方向斜入射为例）：源加 `"theta": 30`
定角度；横向两面（x_min/x_max）设 bloch，k 取**中心频率**的横向波矢
（脉冲是宽带的，Bloch 只对一个 k 严格成立，故带宽过大时斜入射精度会
下降）；纵向两面照常 pml。偷懒可直接 `from_source: true`。

**k=[0,0,0] 时 bloch 退化为 periodic**（相位因子恒为 1）——两者逐位
等价，可当作换边界不出错的 sanity check。

### E.3 网格选型、代价与 refine

网格由 `mesh` 段配置，全部长度 SI（米）。基础步长与回退规则：

```json
"mesh": {"dx": 20e-9, "dy": 20e-9, "dz": 10e-9}
```

回退：`dy` 未设用 `dx`，`dz` 未设用 `dx`。所以教程里只写一行
`"dx": 25e-9` 就是三个方向同一步长。步长决定精度与开销：结果对 dx 的
收敛大约按 dx²（网格色散），步数又 ∝ 1/dx——先粗跑通、再细化验证收敛。
经验：光学波段每个波长至少 **15–20 格**起步，金属/高折射率界面附近再
往上加。

**资源上限**：服务在提交时估算网格总量（含细化增量），超过上限直接
HTTP 400（默认 2×10⁸ 格，上限表见附录 B）；被拒时的错误信息会给出估算值
与上限值。各轴名义格数有保底下限（10 格 = `min_cells` 默认）。

**refine：局部细化**——全域细化最贵（格数与步数双涨），只在小特征附近
加密：

```json
"mesh": {"dx": 50e-9,
          "refine": [{"x_range": [-100e-9, 100e-9],
                       "y_range": [-100e-9, 100e-9],
                       "z_range": [-50e-9, 50e-9],
                       "factor": 2}]}
```

**什么时候该 refine**：局部小特征（缝隙、尖端、薄层）或场梯度大的界面
（等离子体表面）——全域加密浪费，局部 refine 只花在刀刃上。参数语义：

- `factor`：细化倍数，**正整数 ≥2**（非整数提交时被拒，不会静默取整）；
  也可逐轴：`"factor": [2, 2, 4]`；
- `growth_rate`（默认 1.2）：细格到粗格的过渡增长率——细化区边缘网格按
  此比率渐变回基础步长，避免突变界面引入数值反射；设 1.0 表示无渐变直接
  跳变；
- zone 部分越界是**合法**的（逐轴取交集）；完全落在域外（三轴都不相交）
  提交时被拒——否则细化会静默不发生。

**refine 牵动 dt 与步数**：时间步长由**全域最细格**按 CFL 条件决定：
refine factor=2 后最细格约减半，dt 跟着减半，同样物理时长下步数翻倍
——细化是有步数代价的，factor=4 意味着约 4 倍步数。注意最细格可能因区间
量化**略小于**基础步长/factor（例如 50 nm 基础 ×2 的实测最细格 18.6 nm），
dt 相应再低一点。跑完在 `f.summary()`（`/api/jobs/{id}/summary`）核对
`dt` 与 `n_steps`（见 E.7）。

库方实测：同一平板透射问题，均匀网格与 refine 网格（各自配空白参考
归一化）的透射谱在源带宽内一致——同物理、同结果，refine 只省格数不省
步数。

**与平面波源兼容**：refine 网格（轴内非均匀）配平面波源已受支持：服务
自动对齐源校准与主网格的时间轴，不需要手工干预——物理结果与同等效分辨率
的均匀网格一致。

### E.4 材料选型阶梯与拟合收敛

配置里 `materials` 是一个列表，每项一种材料；`geometry` 里的结构用
`material` 名字引用它。选型总原则：**用最简单的能正确描述物理的模型**。

**阶梯一：`const` —— 无损无色散**

```json
{"name": "sio2", "type": "const", "eps": 2.10}
```

**何时用**：材料在你的频段内 n 近似常数（玻璃、介质薄膜）。`eps` 传相对
介电常数（n 的平方），`mu` 同理默认 1。注意：常数 ε/μ 必须为正——负常数
不加色散极点会数值发散，建模金属请走下面的极点或 nk 拟合。

**阶梯二：`lorentz` 手写极点 —— 色散模型已知**

```json
{"name": "disp", "type": "lorentz", "eps_inf": 1.0,
 "poles": [{"kind": "lorentz", "omega_0": 3.770e15,
             "gamma": 6.283e13, "delta_eps": 2.0}]}
```

（ω₀ = 2π×600 THz，γ = 2π×10 THz。）**何时用**：你知道材料的谐振子参数
（文献值、Lorentz/Drude 模型系数），想在宽频段内一致地描述色散。

> **⚠ 极点参数是角频率（rad/s），不是赫兹**。`omega_0`、`gamma`、
> `omega_p` 都要乘 `2π`；`delta_eps`（Δε）是无量纲的静态增量。
> 传成 Hz 是最常见的静默错误——频率直接错 2π 倍。

- **Lorentz 极点**（`kind: "lorentz"`，给 `omega_0`）：束缚电子共振模型，
  适合电介质在共振附近的色散；ω₀ 必须非零（零请走 Drude）；
- **Drude 极点**（`kind: "drude"`，给 `omega_p`）：自由电子（等离子体）
  模型，适合金属；
- 标量参数形式自动展开为三轴向，**任意偏振都有色散**；磁侧极点放
  `mu_poles`（同构）；
- **增益走负振子强度**（`delta_eps` < 0 / Drude 的 ω_p² < 0），接受且有界
  稳定；而 **`gamma` < 0（负阻尼）不是增益通道**——内核在 build 期硬拒
  （无饱和机制的时域增益必发散，作业报错）。

库方实测（25 nm 网格、280–320 THz 带内）：const 平板透射与法布里–珀罗
解析式最大偏差 0.022；手写 lorentz 平板与复折射率解析式均值偏差 0.003
（最大 0.087，容差放宽——色散极点的时域离散误差大于纯网格色散，且解析式
不含网格修正）。

**阶梯三：`add_from_library` / `material_fit` —— 只有实测 n/k 数据时**

**配置里能提交的色散材料只有 `lorentz` pole 节点一种线格式。** 实测 n/k
数据（内置库，或自备三列）不直接进配置——先**拟合成 pole 节点**，再把
节点粘进 `materials`。三条正路（字段与错误码见 §Materials 条目）：

- **GUI（G20）**：工具条 `library` 钮 → 拟合对话框——内置库（37 种）
  或自备三列数据，fit 波段**按当前源频带预填**（可调），拟合出的
  pole 节点直接入 cfg。设计原则：**库里存 nk 数据，pole 永远按波长
  现算**（同一份 Au，可见光与紫外拟出的 pole 不同）；色散材料卡的
  "导出 .material.json" 是冻结特定拟合的逃生口，非库正典。
- **SDK（推荐）**：`f.mat.add_from_library('Au', name='au',
  fit_range=(500e-9, 600e-9), n_drude=1, n_lorentz=3)`——客户端展开糖：
  内部读 nk 库 → `genie.material.fit_nk` → 直接注册 lorentz pole 节点，
  **提交的配置里携带的就是 pole**（本地/云端同构）。拟合需要 scipy——缺失
  时 `ImportError` 指路 `pip install scipy`，不静默降级；拟合不收敛抛
  `ValueError`（消息带原因），**不会再表现为作业 failed**。
- **HTTP / agent**：`POST /api/tools/material_fit`（网关层直实现，
  带 `X-API-Key`；`{"library": "Au",
  "fit_range": [500e-9, 600e-9], "n_drude": 1, "n_lorentz": 3,
  "maxfev": 5000}`，或改用 `nk` 三列传自备数据），把返回的
  `material_node` 原样粘进 `materials`；未收敛或 eps_inf≤0 时
  `material_node` 为 `null` + `warnings` 说明原因。
- **浏览器 UI**：材料拟合面板走浏览器侧离线拟合（同一 `fit_nk` 实现），
  不过服务端端点。

库名怎么查：SDK `genie.material.list_library_materials()`（离线、37 种），
或 `GET /api/tools/nk_library`（含单库 nk 三列）。

> **⚠ 老写法已拒收**：手写配置里的 `{"name": "au", "type":
> "from_library", "library": "Au", ...}` 节点 2026-09 起被内核**拒收**
> （内核只吃 pole），提交即报错，错误消息自带三条迁移指路（端点拟合 /
> SDK 糖 / 直接提交 `type:"lorentz"`）。存量配置按上面的正路改一遍即可
> ——拟合数值与旧的服务器端拟合一致（golden 锁 rel=1e-9）。

**fit_range 收敛注意事项（库方实测）**：拟合范围直接决定 `eps_inf`。以 Au
为例，默认 `fit_range`（400–800 nm）给 eps_inf ≈ 7.6；收窄到 500–600 nm
后 eps_inf ≈ 0.20——高频折射率小于 1，此时**默认 cfl=0.9 跑约 1000 步内
即发散出 NaN（作业 failed）**，而 cfl=0.5 与 0.3 全程稳定。通用对策：

1. 拟合后**先用短 total_time（如 6e-15）试跑**看是否发散，发散则把
   `domain` 里的 `cfl` 降到 0.5（实测即稳）；
2. 或者放宽 `fit_range` 让 eps_inf 回到 >1 的区间；
3. 只信 fit_range 内的频段——拟合在范围外没有约束力。

### E.5 源选型、偏振与带宽可信段

配置里 `source` 是一个列表，每项一个源。字段全表见 §Source 条目；本节讲
**选型与行为**。

| type | 形态 | 典型用途 | 什么时候不用 |
|---|---|---|---|
| `soft_source` | 点/体积电流软源 | 偶极辐射、点探测、快速冒烟测试 | 测透射/反射谱——它向四面八方辐射，不是行波 |
| `plane_wave` | 均匀平面波（单向行波，幅度自动校准） | 照明、透射/反射谱、周期结构 | 关心光斑有限大小/聚焦时（用高斯束） |
| `gaussian_beam` | 高斯束（平面波 + 横向高斯包络 `radius`） | 聚焦照明、有限光斑 | 孔径明显大于域横宽时会被边界截断尾部 |

**软源 vs 平面波：本质差别**。软源在指定位置注入脉冲电流，像一根天线，
**向前向后对称辐射**；平面波以单向行波形式注入，**注入面前方是场、背侧
只剩数值泄漏**。库方实测（25 nm 网格、300 THz、60 THz 带宽）：

- 软源前后等距（±0.6 µm）两点峰值场相对差 **0.00%**；
- 平面波前方峰值 |Ey| = 4.79e-01，注入面背侧 3.83e-02——**单向性约 12 倍**，
  背侧残余是注入面的数值泄漏，不是物理反射波。

所以测平板透射要用平面波（归一化流程建立在单向行波上），而软源适合
"这里有没有场"的快速探测和偶极类问题。

**平面波偏振详解（默认 Ey 的坑）**：

- 默认 `(theta, phi, psi) = (0, 0, 0)`：沿 **+z** 传播、**电场沿 Ey**。
  此时时域监视器 `field: "Ex"` 读到恒 0——不是源没注入，是偏振方向；
  要么读 `Ey`/`all`，要么显式给 `"psi"` 转偏振；
- **`psi` 转偏振**（度）：0 = 垂直入射面的 s 偏振，90° = 平行入射面的
  p 偏振；任意角度是两者的线性组合；
- **`theta`/`phi` 定方向**（度）：theta 是与传播轴的夹角（0 = 正入射，
  合法范围 [0, 180]），phi 是入射面内的方位角（[0, 360)）；越界角度提交时
  直接 422，而不是静默回绕。

**正入射 vs 斜入射的边界配套**：

- **正入射**（theta=0）：横向两对边界用**周期边界**即可（平面波横向均匀，
  周期边界等效无限大横截面，教程即此写法）；
- **斜入射**（theta≠0）：横向边界必须换成 **Bloch** 并成对设置，否则周期
  边界的相位不匹配会在界面产生杂散反射。详见 E.2。

**`from_face`：推荐的贴面注入**

```json
{"type": "plane_wave", "freq": 300e12, "bandwidth": 60e12,
 "name": "pw", "from_face": "z_min"}
```

`"from_face": "z_min"` 一步完成：传播轴钉在 z、方向指向域内（`_min` 面为
+，`_max` 面为 −）、注入面放在该面内侧约 2.5 格（吸收层内缘）、横轴中心取
域中点。它会**覆盖**此前设置的 `center` 与传播轴/方向；`size`（横向窗口）
和 `theta/phi/psi` 可以与它自由组合。不用 `from_face` 时手动给
`"center": [x, y, z]` 定位，或用 `"size"`（恰一槽非正即传播轴）/
`"propagation_axis"` 定轴。

**带宽与可信频段**：源是高斯脉冲，`bandwidth` 决定可信频段——**只有源
带宽内（约 f0 ± bandwidth/2）的频谱幅度有物理意义**，带外只是脉冲谱的
自然滚降。因此频域监视器的频率窗应设得比源带宽宽（见 E.6），解读时只看
带内。

高斯束的 `radius` 语义（库方实测）：它是源平面高斯**孔径半径**——幅度
包络 exp(−r²/2σ²)、σ = r/3，在 r 处截断；对应 1/e² 强度束宽
w = √2/3·r ≈ 0.47·r。想要某束宽 w 就给 radius ≈ 2.12·w。

### E.6 监视器：记什么、何时用、怎么取数

配置里 `monitor` 是一个列表；**监视器只是登记**，不含任何数据。数据在作业
成功后进 `results.npz`，每个监视器一组数组，键名带前缀：`t@名.*`（时域）、
`f@名.*`（频域）、`i@名.*`（折射率分布）。字段全表见 §Monitor 条目。

| type | 记什么 | 什么时候用 |
|---|---|---|
| `time` | 每步的时域场分量 | 看波形、自做 FFT、检查脉冲是否跑完 |
| `freq` | 运行中逐点 DFT 的频谱 | 透射/反射谱、共振频率——不想存海量时域数据时 |
| `index` | ε/μ 材料分布快照 | 跑之前检查结构是否摆对位置 |

```json
{"type": "time", "name": "pt", "center": [0, 0, 0.5e-6],
 "size": [0, 0, 0], "field": "Ey"}
```

- `size` 全零（默认）是点监视器；给一维/二维尺寸得到线/面监视器；
  **null 槽表示该轴全域展开**（体积监视器数据量大，会被资源上限拦）；
  数据形状随维度变化（点监视器的 time 结果是 `(n_t,)`，freq 结果保留尾部
  轴 `(n_f, 1)`）；
- **field 取值集合**：time/freq 用 `"Ex","Ey","Ez","Hx","Hy","Hz"` 或
  `"all"`（默认）；index 用 `"eps"`（默认）、`"mu"`、`"both"`。非法名字
  提交时 422；
- 同类监视器**不能重名**（提交时 422）；跨类同名合法。

**down_sample：正序窗 + 步进**

```json
{"type": "time", "name": "pt", "center": [0, 0, 0.5e-6], "field": "Ey",
 "size": [0, 0, 0],
 "down_sample": {"time_window": [0, 8e-15], "stride": 1}}
```

`time_window: [start, stop]` 只保留窗内样本（秒；**必须 start < stop**，
反序窗会静默得到 0 个样本）；`stride ≥ 1` 每隔 N 步取一样本。什么时候需要：
只关心某个时间段（如直射脉冲段，避开晚期回波），或长仿真里时域数据太大想
降采样（也能过资源上限）。

**apodize：给频谱加渐变收尾**

```json
{"type": "freq", "name": "sp", "field": "Ey",
 "freq": {"center": 300e12, "bw": 120e12, "n": 240},
 "apodize": {"side": "stop", "time_window": [0, 75e-15], "width": 15e-15}}
```

- `side`：`"start"`（头部升起前为 0）、`"stop"`（尾部余弦降到 0 后为 0）、
  `"both"`；`time_window` 定升/降中心，`width` 是斜坡宽度；
- **时机**：脉冲没跑完、或晚期还有回波/尾振时，abrupt 截断会把泄漏甩进
  谱里；`"stop"` 收尾等于把 t > stop 的样本关在谱外。库方实测（薄 PML
  产生晚期回波）：带内谱形相对干净参考的偏差从**无切趾 2.41% 降到切趾
  1.53%**；
- 代价要知道：切趾是对残余场的幅度调制，`width` 给太窄反而把边带甩到
  带外。脉冲已完全衰减、无回波时不需要切趾。

**index 监视器：跑之前就能看结构**。`index` 记录 ε/μ 空间分布。
**注意数据形态**：对体积监视器，npz 里的 `i@名.eps`、`i@名.mu` 是**平铺的
cell 列表**（一维数组，每格一个值），`i@名.x/y/z` 是与之等长的**逐格坐标**
（不是轴刻度）——重构三维分布用 `np.unique` 取各轴坐标再按需 reshape，或
直接按坐标掩码做切面。用来**检查结构**：沿一条线取 ε，看平板边界、材料 n
是否如预期（库方实测：真空区 n 均值 1.0000，SiO2 区 n = 1.449 = √2.10）。
常数材料的 ε 从系数反读，直接得到你配置的 n²。服务还会为 index 监视器
自动生成中心切面预览图。

**频率窗原则：比源带宽宽**。freq 监视器的 `freq: {center, bw, n}` 中
`bw ≥ 0` 且窗口不得越过 0。经验法则：**监视器频率窗设得比源带宽宽**（如源
带宽 60 THz、监视器窗 120 THz）——多出的边缘点用来确认带外只剩脉冲谱的
自然滚降（哪些频段可信见 E.5）。

**time 与 freq 双路的一致性**。库方实测：同一探测点放 time + freq
双监视器，

- time 结果自 FFT 谱峰 300.04 THz vs freq 监视器谱峰 299.25 THz（差 < 1%）；
- 谱峰幅度 224.22 vs 224.37——两者都是同一波形的采样和，应吻合
  （差 < 0.1%）。

两路取数不一致时先怀疑监视器配置不同（位置/field/窗口），而不是服务。

### E.7 作业生命周期与结果交付

一个作业有五个状态，`GET /api/jobs/{id}` 的 `state` 字段随时可查：

```
 queued ──(排队轮到)──▶ running ──▶ succeeded
                          │
                          ├──▶ failed   （运行出错，带 error + log_tail）
                          └──▶ killed   （超时被强制终止）
```

- `queued`：已通过校验与资源检查，在 GPU 队列里排队；
- `running`：已选定一张空闲 GPU，子进程正在装配与推进（返回体里 `gpu`
  字段显示卡号）；
- `succeeded`：正常结束。`results.npz`、`summary.json`、每监视器一张
  `preview_*.png` 已生成；
- `failed`：装配或运行出错。`error` 是一句话结论，`log_tail` 是日志尾部；
  完整日志走 `/api/jobs/{id}/log`；
- `killed`：超过 `run.timeout_s` 被强制终止（默认 3600 s）。

**三条硬规则**：

1. **配置即不可变**。作业一旦提交（HTTP 202），JSON 配置就封存进
   `payload.json`，没有任何"改参数续跑"的接口。改任何参数 = 提交新作业。
   这对应仿真装配的物理事实：网格、边界、源任何一项变动都需要完全重装配。
2. **时长由 domain.total_time 定义**。`domain.total_time`（SI 秒）是
   仿真时长的唯一旋钮，作业推进到网格时间容量为止；步数（n_steps）是
   build 后派生的只读量（见 summary）。想多跑一段就把 total_time 设够
   并提交新作业（服务端不做"接着跑"）。
3. **结果只属于成功终态**。`failed`/`killed` 的作业没有 `results.npz`，
   取结果端点返回 409。别对着失败作业下载空数据。

**校验发生在两个时刻**：

- **提交时（同步，毫秒级）**：JSON 形状错 → HTTP 422（带字段路径）；
  资源超限 → HTTP 400（网格总量 / 步数 / 超时 / 监视器体积四类上限，
  见附录 B）；
- **运行时（异步）**：装配期才会爆的深层组合错误（结构尺寸互相打架、
  材料拟合不收敛等）表现为作业 `failed`——**配置通过提交校验不等于一定
  能跑成**，看 `error` 与日志。

**装配信息在 summary**：`succeeded` 之后 `f.summary()`
（`GET /api/jobs/{id}/summary`）给出 `grid_shape`（三轴格数，含吸收层）、
`dt`（时间步长，秒）、`n_steps`、以及每个监视器的类型与规模。核对网格尺寸
是否如预期，用它而不是靠猜。dt 的量级可用解析式自查（三维均匀网格 CFL
步长）：`dt ≈ cfl · dx / (C0 · √3)`，一致到 0.1% 量级。

**排队与 GPU 分派**：服务单队列串行消化（先稳后快）；每个作业自动挑当前
空闲显存最大的卡。指定卡数：`"run": {"gpu": 3}`（= 3 张卡，设备/链/切轴自动）。
资源上限由管理员配置，超限作业在提交时就拒，不会占着队列排半天然后死。
