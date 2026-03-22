"""
GameDev.tv 课程批量下载器

用法示例：
  python additionpackage/gamedevtv_downloader.py ^
    "https://gamedev.tv/courses/unreal-survival/welcome-to-the-course/7200" ^
    --cookie "./cookies/gamedev.txt"
    --list-only 只输出课程列表

说明：
  - 通过 cookies 文件中的 token 组装 Bearer Token，调用 GameDev.tv 官方 API 枚举课程章节/课时
  - 直接下载每个课时的 HLS(m3u8) 到 MP4
  - 输出到 input/<课程名>/<章节序号 章节名>/<课时序号 课时名>.mp4
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT_DIR = PROJECT_ROOT / "input"
DEFAULT_COOKIE_PATH = PROJECT_ROOT / "cookies" / "gamedev.txt"
API_BASE = "https://prod.gamedev.tv/api"


def sanitize_name(name: str) -> str:
    name = name.replace("：", "_")
    name = re.sub(r"[\\/:*?\"<>|']", "_", name)
    name = re.sub(r"_+", "_", name)
    return name.strip("_. ")


def slugify_title(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.strip().lower())
    return slug.strip("-")


def extract_course_slug(url: str) -> str | None:
    parts = [p for p in urlparse(url).path.split("/") if p]
    if len(parts) >= 2 and parts[0] == "courses":
        return parts[1]
    return None


@dataclass
class LectureItem:
    section_index: int
    section_title: str
    lecture_index: int
    lecture_id: int
    lecture_title: str
    playlist_url: str
    lecture_slug: str

    @property
    def relative_url(self) -> str:
        return f"{self.lecture_slug}/{self.lecture_id}"


class GameDevDownloader:
    def __init__(self, cookie_path: Path, output_dir: Path) -> None:
        self.cookie_path = cookie_path
        self.output_dir = output_dir
        self.session = requests.Session()
        self.token = self._load_cookies(cookie_path)
        self.session.headers.update(
            {
                "Authorization": f"Bearer {self.token}",
                "Referer": "https://gamedev.tv/",
                "Origin": "https://gamedev.tv",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
            }
        )

    def _load_cookies(self, cookie_path: Path) -> str:
        if not cookie_path.is_file():
            raise FileNotFoundError(f"cookies 文件不存在: {cookie_path}")
        jar = MozillaCookieJar(str(cookie_path))
        jar.load(ignore_discard=True, ignore_expires=True)
        for cookie in jar:
            self.session.cookies.set_cookie(cookie)
        token = None
        for cookie in jar:
            if cookie.name == "token":
                token = cookie.value
                break
        if not token:
            raise RuntimeError(
                f"未在 cookies 文件中找到 token: {cookie_path}\n"
                "请确认这是从已登录 GameDev.tv 导出的 Netscape cookies.txt。"
            )
        return token

    def _get_json(self, path: str) -> dict:
        resp = self.session.get(f"{API_BASE}{path}", timeout=30)
        resp.raise_for_status()
        return resp.json()

    def resolve_course_id(self, url: str) -> int:
        """从课程/课时页面 HTML 中提取 courseId。"""
        resp = self.session.get(url, timeout=30)
        resp.raise_for_status()
        html = resp.text

        m = re.search(r'\\?"courseId\\?":\s*(\d+)', html)
        if m:
            return int(m.group(1))

        parsed = urlparse(url)
        if "/dashboard/courses/" in parsed.path:
            m = re.search(r"/dashboard/courses/(\d+)", parsed.path)
            if m:
                return int(m.group(1))

        raise RuntimeError(
            "无法从页面中解析 courseId。\n"
            "请传入已购课程中的课程页或课时页链接，并确保 cookies 有效。"
        )

    def fetch_course(self, course_id: int) -> dict:
        data = self._get_json(f"/courses/my/{course_id}")
        return data["data"]

    def iter_lectures(self, course: dict) -> Iterable[LectureItem]:
        sections = sorted(course.get("sections") or [], key=lambda x: x.get("order") or 0)
        for s_idx, section in enumerate(sections, 1):
            lectures = sorted(section.get("lectures") or [], key=lambda x: x.get("order") or 0)
            for l_idx, lecture in enumerate(lectures, 1):
                video = lecture.get("video") or {}
                playlist = video.get("playListUrl")
                if not playlist:
                    continue
                title = lecture.get("title") or f"Lecture {lecture.get('id')}"
                slug = lecture.get("slug") or slugify_title(title)
                yield LectureItem(
                    section_index=s_idx,
                    section_title=section.get("title") or f"Section {s_idx}",
                    lecture_index=l_idx,
                    lecture_id=int(lecture["id"]),
                    lecture_title=title,
                    playlist_url=playlist,
                    lecture_slug=slug,
                )

    def build_output_path(self, course_title: str, lecture: LectureItem) -> Path:
        course_dir = self.output_dir / sanitize_name(course_title)
        section_dir = course_dir / f"{lecture.section_index:02d} {sanitize_name(lecture.section_title)}"
        filename = f"{lecture.lecture_index:02d} {sanitize_name(lecture.lecture_title)}.mp4"
        return section_dir / filename

    @staticmethod
    def is_good_mp4(path: Path) -> bool:
        return path.is_file() and path.stat().st_size > 2 * 1024 * 1024

    @staticmethod
    def ffprobe_summary(path: Path) -> dict:
        proc = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration,size",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        data = json.loads(proc.stdout or "{}").get("format") or {}
        return {
            "duration": float(data.get("duration") or 0),
            "size": int(data.get("size") or 0),
        }

    def download_hls(self, lecture: LectureItem, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = output_path.with_suffix(".downloading.mp4")
        if tmp_path.exists():
            tmp_path.unlink()

        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "warning",
            "-stats",
            "-y",
            "-i",
            lecture.playlist_url,
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(tmp_path),
        ]
        subprocess.run(cmd, check=True)
        tmp_path.replace(output_path)
        return output_path


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="批量下载 GameDev.tv 课程到 input/")
    p.add_argument("url", help="课程或课时页面链接")
    p.add_argument("--cookie", default=str(DEFAULT_COOKIE_PATH), help="GameDev.tv cookies.txt 路径")
    p.add_argument("--output", default=str(DEFAULT_INPUT_DIR), help="输出根目录，默认 ./input")
    p.add_argument("--list-only", action="store_true", help="仅列出章节与课时，不下载")
    p.add_argument("--limit", type=int, default=0, help="仅下载前 N 节（0=全部）")
    p.add_argument("--force", action="store_true", help="即使文件已存在也重新下载")
    return p


def main() -> None:
    args = build_parser().parse_args()
    downloader = GameDevDownloader(Path(args.cookie), Path(args.output))
    course_slug = extract_course_slug(args.url)

    course_id = downloader.resolve_course_id(args.url)
    course = downloader.fetch_course(course_id)
    course_title = course.get("title") or f"Course {course_id}"
    lectures = list(downloader.iter_lectures(course))
    if not lectures:
        raise RuntimeError("未从课程 API 中解析到任何带视频的课时。")

    print(f"课程: {course_title}")
    print(f"course_id: {course_id}")
    print(f"课时数: {len(lectures)}")

    if args.list_only:
        for lec in lectures:
            print(
                f"[{lec.section_index:02d}.{lec.lecture_index:02d}] "
                f"{lec.section_title} / {lec.lecture_title} -> {lec.relative_url}"
            )
        return

    limit = args.limit if args.limit and args.limit > 0 else len(lectures)
    selected = lectures[:limit]
    for idx, lecture in enumerate(selected, 1):
        out_path = downloader.build_output_path(course_title, lecture)
        print(
            f"\n[{idx}/{len(selected)}] "
            f"{lecture.section_title} / {lecture.lecture_title}"
        )
        if course_slug:
            print(f"  页面: https://gamedev.tv/courses/{course_slug}/{lecture.relative_url}")
        print(f"  输出: {out_path}")
        if out_path.exists() and downloader.is_good_mp4(out_path) and not args.force:
            meta = downloader.ffprobe_summary(out_path)
            print(
                f"  SKIP 已存在 "
                f"(时长 {meta['duration']:.1f}s, 大小 {meta['size'] / 1024 / 1024:.1f} MB)"
            )
            continue
        downloader.download_hls(lecture, out_path)
        meta = downloader.ffprobe_summary(out_path)
        print(
            f"  DONE 完成 (时长 {meta['duration']:.1f}s, 大小 {meta['size'] / 1024 / 1024:.1f} MB)"
        )


if __name__ == "__main__":
    main()
