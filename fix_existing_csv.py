#!/usr/bin/env python3
"""修复现有 positions.csv 文件中的科学计数法问题"""

import csv
import re
from pathlib import Path

def has_scientific_notation(value: str) -> bool:
    """检查字符串是否包含科学计数法"""
    return bool(re.search(r'\d+\.?\d*e[+-]?\d+', str(value).lower()))

def convert_scientific_to_int(value: str) -> str:
    """尝试将科学计数法转换为整数字符串"""
    try:
        # 如果是科学计数法，转换为浮点数再转为整数字符串
        if has_scientific_notation(value):
            num = float(value)
            # 如果是整数，转换为整数字符串（去除小数点）
            if num == int(num):
                return str(int(num))
            else:
                # 如果有小数部分，保留浮点数格式
                return str(num)
        return value
    except (ValueError, OverflowError):
        # 转换失败，返回原值
        return value

def fix_csv_file(csv_path: str, backup: bool = True):
    """
    修复 CSV 文件中的科学计数法问题

    Args:
        csv_path: CSV 文件路径
        backup: 是否创建备份文件
    """
    path = Path(csv_path)

    if not path.exists():
        print(f"❌ 文件不存在: {csv_path}")
        return False

    print(f"🔍 检查文件: {csv_path}")

    # 读取文件
    with open(path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    if not rows:
        print("⚠️  文件为空，无需修复")
        return True

    # 检查哪些字段包含科学计数法
    fields_with_scientific = set()
    fixed_count = 0

    for row in rows:
        for field, value in row.items():
            if value and has_scientific_notation(value):
                fields_with_scientific.add(field)

    if not fields_with_scientific:
        print("✅ 未检测到科学计数法，无需修复")
        return True

    print(f"⚠️  检测到以下字段包含科学计数法: {fields_with_scientific}")

    # 创建备份
    if backup:
        backup_path = path.with_suffix('.csv.backup')
        import shutil
        shutil.copy2(path, backup_path)
        print(f"📦 已创建备份: {backup_path}")

    # 修复数据
    print("\n🔧 开始修复...")
    for row in rows:
        for field in fields_with_scientific:
            if field in row and row[field]:
                old_value = row[field]
                new_value = convert_scientific_to_int(old_value)
                if old_value != new_value:
                    print(f"  {field}: {old_value} → {new_value}")
                    row[field] = new_value
                    fixed_count += 1

    # 写回文件（使用 QUOTE_NONNUMERIC 防止再次出现问题）
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_NONNUMERIC)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n✅ 修复完成! 共修复 {fixed_count} 个字段")
    print(f"📄 已更新文件: {csv_path}")

    return True

def main():
    """主函数"""
    positions_csv = "./data/positions.csv"

    print("=" * 60)
    print("CSV 科学计数法修复工具")
    print("=" * 60)
    print()

    # 检查文件是否存在
    if not Path(positions_csv).exists():
        print(f"ℹ️  文件不存在: {positions_csv}")
        print("   如果这是新项目，无需修复。")
        return

    # 修复文件
    fix_csv_file(positions_csv, backup=True)

    print()
    print("=" * 60)
    print("提示:")
    print("  - 如果原始数据已损坏，可能无法完全恢复")
    print("  - 科学计数法如 8.81318e+76 可能已丢失精度")
    print("  - 建议检查修复后的数据是否正确")
    print("  - 备份文件保存为: positions.csv.backup")
    print("=" * 60)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
