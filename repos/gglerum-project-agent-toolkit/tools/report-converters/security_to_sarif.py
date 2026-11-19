from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from report_io import read_json, write_json, entry, load_report
import json
import sys

def get_sarif_boilerplate(tool_name):
    return {
        "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": tool_name,
                        "rules": []
                    }
                },
                "results": []
            }
        ]
    }

def convert_gitleaks(input_file, output_file):
    data = load_report(input_file, "gitleaks")


    sarif = get_sarif_boilerplate("gitleaks")
    rules = {}
    results = []

    # Gitleaks output is a list of objects
    if isinstance(data, list):
        for finding in data:
            rule_id = finding.get('RuleID', 'generic-secret')
            description = finding.get('Description', 'Potential Secret found')
            file_path = finding.get('File', '')
            start_line = finding.get('StartLine', 1)
            end_line = finding.get('EndLine', 1)
            start_column = finding.get('StartColumn', 1)
            end_column = finding.get('EndColumn', 1)
            
            # Map rule
            if rule_id not in rules:
                rules[rule_id] = {
                    "id": rule_id,
                    "shortDescription": {
                        "text": description
                    }
                }
            
            # Create result
            results.append({
                "ruleId": rule_id,
                "level": "error",
                "message": {
                    "text": f"Secret found: {description}"
                },
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {
                                "uri": file_path
                            },
                            "region": {
                                "startLine": start_line,
                                "endLine": end_line,
                                "startColumn": start_column,
                                "endColumn": end_column
                            }
                        }
                    }
                ]
            })

    sarif['runs'][0]['tool']['driver']['rules'] = list(rules.values())
    sarif['runs'][0]['results'] = results

    write_json(output_file, sarif)
    print(f"Converted Gitleaks JSON to SARIF: {output_file}")

def convert_trivy(input_file, output_file):
    data = load_report(input_file, "trivy")


    sarif = get_sarif_boilerplate("Trivy")
    rules = {}
    results = []
    
    # Trivy structure: { "Results": [ ... ] }
    scan_results = data.get('Results', [])
    
    if scan_results:
        for target in scan_results:
            target_file = target.get('Target', '')
            
            # Vulnerabilities
            for vuln in target.get('Vulnerabilities', []) or []:
                vuln_id = vuln.get('VulnerabilityID', '')
                pkg_name = vuln.get('PkgName', '')
                installed_version = vuln.get('InstalledVersion', '')
                fixed_version = vuln.get('FixedVersion', '')
                title = vuln.get('Title', '')
                description = vuln.get('Description', '')
                severity = vuln.get('Severity', 'UNKNOWN')
                
                level = "warning"
                if severity in ["CRITICAL", "HIGH"]:
                    level = "error"
                elif severity == "LOW":
                    level = "note"

                if vuln_id not in rules:
                    rules[vuln_id] = {
                        "id": vuln_id,
                        "shortDescription": {
                            "text": title or vuln_id
                        },
                        "fullDescription": {
                            "text": description
                        },
                        "helpUri": vuln.get('PrimaryURL', '')
                    }

                results.append({
                    "ruleId": vuln_id,
                    "level": level,
                    "message": {
                        "text": f"{pkg_name} ({installed_version}) is vulnerable to {vuln_id}. Fixed in: {fixed_version}"
                    },
                    "locations": [
                        {
                            "physicalLocation": {
                                "artifactLocation": {
                                    "uri": target_file
                                },
                                "region": {
                                    "startLine": 1 
                                }
                            }
                        }
                    ]
                })

            # Misconfigurations
            for misconf in target.get('Misconfigurations', []) or []:
                misconf_id = misconf.get('ID', '')
                title = misconf.get('Title', '')
                desc = misconf.get('Description', '')
                severity = misconf.get('Severity', 'UNKNOWN')
                
                # Handling IacMetadata to get lines
                iac_meta = misconf.get('IacMetadata', {})
                start_line = iac_meta.get('StartLine', 1)
                end_line = iac_meta.get('EndLine', 1)
                
                if misconf_id not in rules:
                     rules[misconf_id] = {
                        "id": misconf_id,
                        "shortDescription": {"text": title},
                        "fullDescription": {"text": desc}
                     }
                
                level = "warning"
                if severity in ["CRITICAL", "HIGH"]:
                     level = "error"

                results.append({
                    "ruleId": misconf_id,
                    "level": level,
                    "message": {"text": misconf.get('Message', title)},
                    "locations": [{
                        "physicalLocation": {
                            "artifactLocation": {"uri": target_file},
                            "region": {"startLine": start_line, "endLine": end_line}
                        }
                    }]
                })

    sarif['runs'][0]['tool']['driver']['rules'] = list(rules.values())
    sarif['runs'][0]['results'] = results

    write_json(output_file, sarif)
    print(f"Converted Trivy JSON to SARIF: {output_file}")

def cli():
    if len(sys.argv) != 4:
        print("Usage: python3 security_to_sarif.py <tool> <input_json> <output_sarif>")
        sys.exit(1)
        
    tool = sys.argv[1]
    input_file = sys.argv[2]
    output_file = sys.argv[3]
    
    if tool == 'trivy':
        convert_trivy(input_file, output_file)
    elif tool == 'gitleaks':
        convert_gitleaks(input_file, output_file)
    else:
        print(f"Unknown tool: {tool}")
        sys.exit(1)


if __name__ == "__main__":
    sys.exit(entry(cli))
