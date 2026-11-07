# export_excel.py — T-10：產生可在 Excel 比對的驗算工作簿
# 把引擎用的同一段價格寫進 Excel，並以「真正的 Excel 公式」重算每個指標，
# 旁邊附上引擎值與差異。開啟 Excel 後公式會自動計算，可當答辯時的手算佐證。
# 用法：python -m scripts.export_excel ["展示-ETF型"]
from __future__ import annotations

import sys

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from app.db import get_conn
from app.services.price_service import get_prices_df, get_sector_map
from app.services.risk_engine import LOOKBACK_DAYS, RISK_FREE_RATE, analyze

OUT = "verification.xlsx"
HEAD = Font(bold=True)
HFILL = PatternFill("solid", fgColor="DDE7FB")


def _load_portfolio(name: str):
    conn = get_conn()
    try:
        like = f"%{name}%"
        u = conn.execute(
            "SELECT id FROM users WHERE display_name LIKE ? ORDER BY id LIMIT 1", (like,)
        ).fetchone()
        if not u:
            raise SystemExit(f"找不到名稱含「{name}」的 demo 帳號，請先 seed_demo。")
        rows = conn.execute(
            "SELECT symbol, shares FROM holdings WHERE user_id = ? ORDER BY symbol", (u["id"],)
        ).fetchall()
    finally:
        conn.close()
    return [(r["symbol"], float(r["shares"])) for r in rows]


def main(argv) -> int:
    name = argv[0] if argv else "ETF型"
    holdings = _load_portfolio(name)
    symbols = [s for s, _ in holdings]
    shares = [q for _, q in holdings]
    k = len(symbols)

    prices_all = get_prices_df(symbols)
    sector_map = get_sector_map(symbols)

    # 取引擎實際使用的視窗（共同交易日、最近 252+1 天）
    prices = prices_all.sort_index().ffill(limit=5)
    sub = prices[symbols].dropna(how="any").tail(LOOKBACK_DAYS + 1)
    m = len(sub)            # 價格列數（約 253）
    n = m - 1              # 報酬列數（約 252）
    last_price = sub.iloc[-1]

    # 權重（寫死為數值，Excel 其餘指標引用它）
    v = pd.Series(shares, index=symbols) * last_price.reindex(symbols)
    weights = (v / v.sum())

    eng = analyze(pd.DataFrame({"symbol": symbols, "shares": shares}),
                  prices_all, sector_map)["metrics"]

    wb = Workbook()

    # ---- Sheet 1: prices ----
    wp = wb.active
    wp.title = "prices"
    wp.append(["Date"] + symbols)
    for c in range(1, k + 2):
        wp.cell(row=1, column=c).font = HEAD
        wp.cell(row=1, column=c).fill = HFILL
    for d, row in sub.iterrows():
        wp.append([pd.Timestamp(d).strftime("%Y-%m-%d")] + [float(x) for x in row.values])

    # 欄位字母
    sym_cols = [get_column_letter(2 + i) for i in range(k)]      # 個股欄 B,C,...
    port_col = get_column_letter(2 + k)                          # 組合報酬
    wlth_col = get_column_letter(3 + k)                          # 財富
    peak_col = get_column_letter(4 + k)                          # 歷史高
    draw_col = get_column_letter(5 + k)                          # 回撤
    onep_col = get_column_letter(6 + k)                          # 1+報酬

    # ---- Sheet 2: returns（公式）----
    wr = wb.create_sheet("returns")
    # 第 1 列：權重（放在各個股欄下）
    wr.cell(row=1, column=1, value="權重→").font = HEAD
    for i, col in enumerate(sym_cols):
        c = wr.cell(row=1, column=2 + i, value=round(float(weights.iloc[i]), 12))
        c.font = HEAD
    # 第 2 列：表頭
    headers = ["Date"] + [f"{s} 日報酬" for s in symbols] + \
              ["組合日報酬", "財富(起1)", "歷史高", "回撤", "1+報酬"]
    wr.append([None])  # 佔第1列已寫
    for j, h in enumerate(headers, start=1):
        c = wr.cell(row=2, column=j, value=h)
        c.font = HEAD
        c.fill = HFILL
    # 資料列 3..(2+n)
    for i in range(n):
        R = 3 + i          # returns 列
        PR = R             # prices 列（對齊：returns 列 R 用 prices 列 R 與 R-1）
        wr.cell(row=R, column=1, value=f"=prices!A{PR}")
        for ci, col in enumerate(sym_cols):
            wr.cell(row=R, column=2 + ci,
                    value=f"=prices!{col}{PR}/prices!{col}{PR-1}-1")
        wr.cell(row=R, column=2 + k,
                value=f"=SUMPRODUCT(${sym_cols[0]}$1:${sym_cols[-1]}$1,"
                      f"{sym_cols[0]}{R}:{sym_cols[-1]}{R})")
        if i == 0:
            wr.cell(row=R, column=3 + k, value=f"=1*(1+{port_col}{R})")
            wr.cell(row=R, column=4 + k, value=f"=MAX(1,{wlth_col}{R})")
        else:
            wr.cell(row=R, column=3 + k, value=f"={wlth_col}{R-1}*(1+{port_col}{R})")
            wr.cell(row=R, column=4 + k, value=f"=MAX({peak_col}{R-1},{wlth_col}{R})")
        wr.cell(row=R, column=5 + k, value=f"={wlth_col}{R}/{peak_col}{R}-1")
        wr.cell(row=R, column=6 + k, value=f"=1+{port_col}{R}")

    r0, r1 = 3, 2 + n       # 資料列範圍
    PORT = f"{port_col}{r0}:{port_col}{r1}"
    ONEP = f"{onep_col}{r0}:{onep_col}{r1}"
    DRAW = f"{draw_col}{r0}:{draw_col}{r1}"
    WRANGE = f"{sym_cols[0]}1:{sym_cols[-1]}1"

    # ---- Sheet 3: metrics（公式 vs 引擎）----
    wm = wb.create_sheet("metrics")
    wm.append(["指標", "Excel 公式重算", "引擎值", "差異(絕對值)"])
    for c in range(1, 5):
        wm.cell(row=1, column=c).font = HEAD
        wm.cell(row=1, column=c).fill = HFILL

    rows_spec = [
        ("觀察交易日數 n", f"=COUNT(returns!{PORT})", eng["n_observations"]),
        ("最大單一持股 top1", f"=MAX(returns!{WRANGE})", eng["top1_weight"]),
        ("股票 HHI", f"=SUMPRODUCT(returns!{WRANGE},returns!{WRANGE})", eng["stock_hhi"]),
        ("有效持股數 Neff",
         f"=1/SUMPRODUCT(returns!{WRANGE},returns!{WRANGE})", eng["effective_n"]),
        ("年化波動度", f"=STDEV.S(returns!{PORT})*SQRT(252)", eng["volatility"]),
        ("年化報酬",
         f"=PRODUCT(returns!{ONEP})^(252/COUNT(returns!{PORT}))-1", eng["annual_return"]),
        ("夏普值",
         f"=(PRODUCT(returns!{ONEP})^(252/COUNT(returns!{PORT}))-1-{RISK_FREE_RATE})"
         f"/(STDEV.S(returns!{PORT})*SQRT(252))", eng["sharpe"]),
        ("最大回撤 MDD", f"=MIN(returns!{DRAW})", eng["max_drawdown"]),
        ("歷史 VaR 95%(單日)",
         f"=MAX(0,-PERCENTILE.INC(returns!{PORT},0.05))", eng["var_95_1d"]),
    ]
    for ri, (label, formula, engval) in enumerate(rows_spec, start=2):
        wm.cell(row=ri, column=1, value=label)
        wm.cell(row=ri, column=2, value=formula)
        wm.cell(row=ri, column=3, value=round(float(engval), 10))
        wm.cell(row=ri, column=4, value=f"=ABS(B{ri}-C{ri})")

    # 產業 HHI：用 SUMIF 依產業彙總權重再平方相加
    ws = wb.create_sheet("sectors")
    ws.append(["symbol", "權重", "產業"])
    for c in range(1, 4):
        ws.cell(row=1, column=c).font = HEAD
        ws.cell(row=1, column=c).fill = HFILL
    for i, s in enumerate(symbols):
        ws.cell(row=2 + i, column=1, value=s)
        ws.cell(row=2 + i, column=2, value=round(float(weights.iloc[i]), 12))
        ws.cell(row=2 + i, column=3, value=sector_map.get(s) or "未分類")
    uniq = sorted(set((sector_map.get(s) or "未分類") for s in symbols))
    # 每個產業的權重與平方
    base = 2 + k + 1
    ws.cell(row=base - 1, column=5, value="產業").font = HEAD
    ws.cell(row=base - 1, column=6, value="產業權重").font = HEAD
    sq_cells = []
    for i, sec in enumerate(uniq):
        rr = base + i
        ws.cell(row=rr, column=5, value=sec)
        ws.cell(row=rr, column=6,
                value=f'=SUMIF(C2:C{1+k},E{rr},B2:B{1+k})')
        sq_cells.append(f"F{rr}^2")
    ws.cell(row=base + len(uniq) + 1, column=5, value="產業 HHI").font = HEAD
    ws.cell(row=base + len(uniq) + 1, column=6, value=f"={'+'.join(sq_cells)}")
    # 在 metrics 補一列產業 HHI
    rsec = len(rows_spec) + 2
    wm.cell(row=rsec, column=1, value="產業 HHI")
    wm.cell(row=rsec, column=2, value=f"=sectors!F{base + len(uniq) + 1}")
    wm.cell(row=rsec, column=3, value=round(float(eng["sector_hhi"]), 10))
    wm.cell(row=rsec, column=4, value=f"=ABS(B{rsec}-C{rsec})")

    for w in (wm, ws):
        for col in range(1, 7):
            w.column_dimensions[get_column_letter(col)].width = 20

    wb.save(OUT)
    print(f"已產生 {OUT}（投組：{name}；{k} 檔、{n} 個交易日）")
    print("開啟 Excel 後，metrics 分頁的『差異』欄應全為 0（或 ~1e-16），代表 Excel 公式與引擎一致。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
