# -*- coding: utf-8 -*-
# =============================================================
#  CyberPi + AI Camera 2.0  ボール追従プログラム
# =============================================================
#  動作仕様:
#    ・AI Camera 2.0 でボール（色のかたまり = Blob）を検知する
#    ・赤いボール  -> ボールに向かって追従。距離は約10cmを保つ
#    ・青いボール  -> ボールからそっぽを向く（反対方向を向く）
#    ・ボールなし  -> その場で停止
#
#  対象ハードウェア:
#    ・CyberPi（mBot2 シャーシに搭載してエンコーダモーターで走行）
#    ・AI Camera 2.0（mBuild で CyberPi に接続）
#
#  実行方法:
#    mBlock の Python エディタにこのファイルを貼り付けて CyberPi に
#    アップロードしてください（「アップロードモード」で実行）。
# =============================================================

import cyberpi
import mbot2
import time

# AI Camera 2.0 を Python から使う場合のモジュール名は、mBlock の
# 「AI Camera 2.0」拡張で生成されるコードに合わせてください。
# 下の get_ball() 内のコメントに対応表をまとめています。
import ai_camera   # ← 実機の拡張に合わせて読み替えてください


# -------------------------------------------------------------
#  調整用パラメータ（実機に合わせてキャリブレーションする）
# -------------------------------------------------------------

# --- カメラ画面の中心 ---------------------------------------
# AI Camera 2.0 が返す X 座標系の「中央」の値。
# 解像度が 320x240 なら中心 X は 160。実機の値に合わせること。
FRAME_CENTER_X = 160

# --- 距離（=ボールの見かけの大きさ）の目標値 ----------------
# ボールが約10cmの位置にあるとき、カメラが返す Blob の「幅(W)」
# のピクセル値を入れる。近いほど W は大きくなる。
#   手順: 赤ボールを実際に10cm前に置き、画面に出る W の値を読んで設定。
TARGET_WIDTH = 80          # 10cmのときの幅(px)。要キャリブレーション
WIDTH_TOLERANCE = 10       # この範囲内なら「ちょうど良い距離」とみなす

# --- 制御ゲイン（P制御） ------------------------------------
KP_TURN = 0.25             # 左右ずれ -> 旋回量への係数
KP_DRIVE = 0.6             # 距離ずれ -> 前後速度への係数

# --- 速度の上限（mBot2 のスピード単位） ---------------------
MAX_SPEED = 60             # 前後・旋回の最大スピード
MIN_BLOB_WIDTH = 5         # これ未満の小さな検出はノイズとして無視

# --- ループ周期 ---------------------------------------------
LOOP_INTERVAL = 0.05       # 秒（約20Hzで制御）


# -------------------------------------------------------------
#  ユーティリティ
# -------------------------------------------------------------
def clamp(value, low, high):
    """value を [low, high] の範囲に収める"""
    if value < low:
        return low
    if value > high:
        return high
    return value


# -------------------------------------------------------------
#  カメラ読み取り
# -------------------------------------------------------------
def get_ball():
    """
    AI Camera 2.0 から最も大きいボール(Blob)を1つ取得する。

    戻り値: (color, x, y, w, h)
        color : "red" / "blue" / その他
        x, y  : Blob 中心の座標
        w, h  : Blob の幅・高さ（大きいほど近い）
    ボールが見つからないときは None を返す。

    --------------------------------------------------------------
    ★実機との対応（mBlock「AI Camera 2.0」ブロック → Python）★
      ・「色認識(Blob)を開始する」ブロック
            -> ai_camera.start_blob_recognition()  などで開始
      ・検出数 / 各 Blob の 色・X・Y・W・H を取得するブロック
            -> ai_camera.get_blob_count()
               ai_camera.get_blob_color(i)
               ai_camera.get_blob_x(i) / _y(i) / _w(i) / _h(i)
      実際の関数名は拡張が生成するコードに合わせて書き換えてください。
    --------------------------------------------------------------
    """
    try:
        count = ai_camera.get_blob_count()
    except Exception:
        # カメラ未対応・通信エラー時は安全側（ボールなし扱い）
        return None

    if not count:
        return None

    # 一番大きい（=一番近い）Blob を選ぶ
    best = None
    best_area = 0
    for i in range(count):
        w = ai_camera.get_blob_w(i)
        h = ai_camera.get_blob_h(i)
        area = w * h
        if area > best_area and w >= MIN_BLOB_WIDTH:
            best_area = area
            best = (
                ai_camera.get_blob_color(i),
                ai_camera.get_blob_x(i),
                ai_camera.get_blob_y(i),
                w,
                h,
            )
    return best


# -------------------------------------------------------------
#  動作: 赤ボールに追従して距離10cmを保つ
# -------------------------------------------------------------
def follow_red(x, w):
    """
    赤ボールを画面中央に保ちつつ、見かけの幅が TARGET_WIDTH に
    なるよう前後して、約10cmの距離を維持する。
    """
    # 左右のずれ（プラス=ボールが右）-> 旋回成分
    error_x = x - FRAME_CENTER_X
    turn = KP_TURN * error_x

    # 距離のずれ。w が小さい=遠い=前進、w が大きい=近い=後退
    width_error = TARGET_WIDTH - w
    if abs(width_error) <= WIDTH_TOLERANCE:
        drive = 0                       # ちょうど10cm付近 -> 前後しない
    else:
        drive = KP_DRIVE * width_error  # 遠ければ正(前進)、近ければ負(後退)

    drive = clamp(drive, -MAX_SPEED, MAX_SPEED)
    turn = clamp(turn, -MAX_SPEED, MAX_SPEED)

    # 差動駆動: 右にボールがある(turn>0)とき右に曲がる
    left_speed = clamp(drive + turn, -MAX_SPEED, MAX_SPEED)
    right_speed = clamp(drive - turn, -MAX_SPEED, MAX_SPEED)

    # mBot2 の左右モーターへ速度指令
    mbot2.drive_speed(left_speed, right_speed)


# -------------------------------------------------------------
#  動作: 青ボールからそっぽを向く
# -------------------------------------------------------------
def turn_away_from_blue(x):
    """
    青ボールが見える側と反対方向にその場で旋回して顔を背ける。
    ボールが視界の中央付近にあるうちは回り続ける。
    """
    error_x = x - FRAME_CENTER_X
    if error_x >= 0:
        # ボールが右 -> 左へ回って背を向ける
        mbot2.drive_speed(-MAX_SPEED, MAX_SPEED)
    else:
        # ボールが左 -> 右へ回って背を向ける
        mbot2.drive_speed(MAX_SPEED, -MAX_SPEED)


# -------------------------------------------------------------
#  停止 + LED 表示
# -------------------------------------------------------------
def stop():
    mbot2.drive_speed(0, 0)


def show_state(color):
    """検知した色を CyberPi の LED と画面に表示してフィードバック"""
    if color == "red":
        cyberpi.led.on(255, 0, 0)
        cyberpi.display.show_label("RED: FOLLOW", 16, "center")
    elif color == "blue":
        cyberpi.led.on(0, 0, 255)
        cyberpi.display.show_label("BLUE: TURN AWAY", 16, "center")
    else:
        cyberpi.led.off()
        cyberpi.display.show_label("NO BALL", 16, "center")


# -------------------------------------------------------------
#  メインループ
# -------------------------------------------------------------
def main():
    # カメラの色認識(Blob)を開始
    try:
        ai_camera.start_blob_recognition()
    except Exception:
        pass

    cyberpi.console.println("Ball tracking start")

    while True:
        ball = get_ball()

        if ball is None:
            stop()
            show_state(None)
        else:
            color, x, y, w, h = ball
            if color == "red":
                show_state("red")
                follow_red(x, w)
            elif color == "blue":
                show_state("blue")
                turn_away_from_blue(x)
            else:
                # 赤・青以外の色は無視して停止
                stop()
                show_state(None)

        time.sleep(LOOP_INTERVAL)


# CyberPi 起動時に実行
main()
