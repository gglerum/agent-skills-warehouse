from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from report_io import read_json, write_json, entry, load_report
import json
import sys
import os
import re
import xml.etree.ElementTree as ET

# Helper to ensure unique rules are added
def ensure_rule(rules, rule_id, engine_id, name, description, attribute, quality, severity):
    if not any(r['id'] == rule_id for r in rules):
        rules.append({
            "id": rule_id,
            "engineId": engine_id,
            "name": name,
            "description": description,
            "cleanCodeAttribute": attribute,
            "impacts": [
                {
                    "softwareQuality": quality,
                    "severity": severity
                }
            ]
        })

def convert_rector(input_file, output_file):
    data = load_report(input_file, "rector")


    rules = []
    issues = []
    
    for file_diff in data.get('file_diffs', []):
        file_path = file_diff.get('file')
        diff_content = file_diff.get('diff', '')
        
        # Try to find start line
        start_line = 1
        match = re.search(r'@@ -(\d+)', diff_content)
        if match:
            start_line = int(match.group(1))

        # Clean up diff
        display_diff = diff_content
        if len(display_diff) > 3000:
            display_diff = display_diff[:3000] + "\n... (truncated)"

        for rule_name in file_diff.get('applied_rectors', []):
            ensure_rule(rules, rule_name, "rector", 
                        f"Rector: {rule_name}", 
                        f"Rector suggested refactoring.\nRule: {rule_name}", 
                        "EFFICIENT", "MAINTAINABILITY", "MEDIUM")

            issues.append({
                "ruleId": rule_name,
                "primaryLocation": {
                    "message": f"Refactoring suggested:\n\n{display_diff}",
                    "filePath": file_path,
                    "textRange": {
                        "startLine": start_line
                    }
                }
            })

    write_json(output_file, {"rules": rules, "issues": issues})
    print(f"Converted Rector issues to {output_file}")


def convert_deptrac(input_file, output_file):
    data = load_report(input_file, "deptrac")


    rules = []
    issues = []
    cwd = os.getcwd()
    
    rule_id = "architecture_violation"
    ensure_rule(rules, rule_id, "deptrac", 
                "Architecture Violation", 
                "Dependency rule violation detected by Deptrac", 
                "MODULAR", "MAINTAINABILITY", "HIGH")

    files = data.get('files', {})
    if not isinstance(files, dict):
        files = {}
    for abs_path, file_data in files.items():
        rel_path = os.path.relpath(abs_path, cwd) if abs_path.startswith('/') else abs_path
        
        for message in file_data.get('messages', []):
            issues.append({
                "ruleId": rule_id,
                "primaryLocation": {
                    "message": message.get('message'),
                    "filePath": rel_path,
                    "textRange": {
                        "startLine": message.get('line', 1)
                    }
                }
            })

    write_json(output_file, {"rules": rules, "issues": issues})
    print(f"Converted Deptrac issues to {output_file}")


def convert_pint(input_file, output_file):
    root = ET.parse(input_file).getroot()
    if root.tag != "checkstyle":
        raise ValueError("expected Checkstyle XML")

    rules = []
    issues = []
    cwd = os.getcwd()
    
    if root is not None:
        for file_elem in root.findall('file'):
            abs_path = file_elem.get('name')
            rel_path = os.path.relpath(abs_path, cwd) if abs_path.startswith('/') else abs_path

            for error_elem in file_elem.findall('error'):
                source = error_elem.get('source', 'unknown')
                message = error_elem.get('message', 'Unknown error')
                severity = error_elem.get('severity', 'info')
                
                sonar_severity = "MEDIUM"
                if severity == "error":
                    sonar_severity = "HIGH"
                
                ensure_rule(rules, source, "pint", 
                            f"Pint: {source}", 
                            "Code style violation reported by Pint/PHP-CS-Fixer", 
                            "FORMATTED", "MAINTAINABILITY", sonar_severity)

                line = error_elem.get('line')
                start_line = int(line) if line else 1

                issues.append({
                    "ruleId": source,
                    "primaryLocation": {
                        "message": message,
                        "filePath": rel_path,
                        "textRange": {
                            "startLine": start_line
                        }
                    }
                })

    write_json(output_file, {"rules": rules, "issues": issues})
    print(f"Converted Pint issues to {output_file}")


def convert_infection(input_file, output_file):
    data = load_report(input_file, "infection")


    rules = []
    issues = []
    
    for item in data:
        description = item.get('description', 'Mutation')
        location = item.get('location', {})
        path = location.get('path', '')
        lines = location.get('lines', {})
        begin_line = lines.get('begin', 1)

        rule_id = "mutation"
        if ":" in description:
            rule_id = description.split(":")[0].strip()

        ensure_rule(rules, rule_id, "infection", 
                    f"Infection: {rule_id}", 
                    "Mutation escaped: Tests did not detect this change.", 
                    "TESTED", "RELIABILITY", "MEDIUM")

        issues.append({
            "ruleId": rule_id,
            "primaryLocation": {
                "message": f"Mutation not killed: {description}",
                "filePath": path,
                "textRange": {
                    "startLine": begin_line
                }
            }
        })

    write_json(output_file, {"rules": rules, "issues": issues})
    print(f"Converted Infection issues to {output_file}")


def convert_cspell(input_file, output_file):
    data = load_report(input_file, "cspell")


    rules = []
    issues = []
    
    rule_id = "spelling"
    ensure_rule(rules, rule_id, "cspell", 
                "Spelling Error", 
                "Possible generic spelling error.", 
                "IDENTIFIABLE", "MAINTAINABILITY", "LOW")

    for issue in data.get('issues', []):
        uri = issue.get('uri', '')
        path_decoded = uri.replace('file://', '')
        # Try relative
        try:
             file_path = os.path.relpath(path_decoded, os.getcwd())
        except ValueError:
             file_path = path_decoded

        text = issue.get('text', '')
        row = issue.get('row', 1)
        col = issue.get('col', 1)
        
        issues.append({
            "ruleId": rule_id,
            "primaryLocation": {
                "message": f"Unknown word: '{text}'",
                "filePath": file_path,
                "textRange": {
                    "startLine": row,
                    "startColumn": col
                }
            }
        })

    write_json(output_file, {"rules": rules, "issues": issues})
    print(f"Converted CSpell issues to {output_file}")

# Note: Composer Audit, Pa11y, ZAP are now largely handled by SARIF or other means,
# but keeping stubs or handling them if still called. 
# ZAP is specifically mentioned in sonar properties still as zap-report-sonar.json

def convert_zap(input_file, output_file):
    data = load_report(input_file, "zap")


    rules = []
    issues = []
    
    for site in data.get('site', []):
        for alert in site.get('alerts', []):
            plugin_id = alert.get('pluginid', 'unknown')
            alert_name = alert.get('alert', 'Unknown Alert')
            risk_code = alert.get('riskcode', '0')
            description = alert.get('desc', '')
            
            # Map risk code to SonarQube severity
            severity = "LOW"
            if risk_code == '3': # High
                severity = "HIGH"
            elif risk_code == '2': # Medium
                severity = "MEDIUM"
            
            ensure_rule(rules, plugin_id, "zap", 
                        f"ZAP: {alert_name}", 
                        description, 
                        "TRUSTWORTHY", "SECURITY", severity)

            full_message = f"{alert_name}"
            
            for instance in alert.get('instances', []):
                uri = instance.get('uri', '')
                method = instance.get('method', '')
                
                instance_message = f"{full_message} ({method} {uri})"

                file_path = "public/index.php"

                issues.append({
                    "ruleId": plugin_id,
                    "primaryLocation": {
                        "message": instance_message,
                        "filePath": file_path,
                        "textRange": {
                            "startLine": 1
                        }
                    }
                })

    write_json(output_file, {"rules": rules, "issues": issues})
    print(f"Converted ZAP issues to {output_file}")


def convert_composer_audit(input_file, output_file):
    from composer_audit_to_sarif import convert_to_sarif
    convert_to_sarif(input_file, output_file)


def cli():
    if len(sys.argv) < 4:
        print("Usage: python3 convert_reports.py [tool] [input] [output]")
        sys.exit(1)

    tool = sys.argv[1]
    input_path = sys.argv[2]
    output_path = sys.argv[3]

    if tool == 'rector':
        convert_rector(input_path, output_path)
    elif tool == 'deptrac':
        convert_deptrac(input_path, output_path)
    elif tool == 'pint':
        convert_pint(input_path, output_path)
    elif tool == 'infection':
        convert_infection(input_path, output_path)
    elif tool == 'cspell':
        convert_cspell(input_path, output_path)
    elif tool == 'zap':
        convert_zap(input_path, output_path)
    elif tool == 'composer-audit':
         convert_composer_audit(input_path, output_path)
    else:
        print(f"Unknown tool: {tool}")


if __name__ == "__main__":
    sys.exit(entry(cli))
