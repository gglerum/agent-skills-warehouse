from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from report_io import read_json, write_json, entry, load_report
import json
import sys

def convert_to_sarif(input_file, output_file):
    data = load_report(input_file, "composer")


    results = []
    rules = []
    rule_ids = set()

    # Surface scan infrastructure failures so SonarQube shows an explicit warning.
    if data.get('__audit_failed__') is True:
        rule_id = "composer-audit-failed"
        rules.append({
            "id": rule_id,
            "shortDescription": {
                "text": "Composer audit did not complete"
            },
            "fullDescription": {
                "text": data.get('message', 'composer audit failed before advisory data could be collected')
            }
        })
        results.append({
            "ruleId": rule_id,
            "level": "warning",
            "message": {
                "text": data.get('message', 'composer audit failed before advisory data could be collected')
            },
            "locations": [
                {
                    "physicalLocation": {
                        "artifactLocation": {
                            "uri": "composer.lock"
                        },
                        "region": {
                            "startLine": 1,
                            "startColumn": 1
                        }
                    }
                }
            ]
        })
        rule_ids.add(rule_id)

    # Handle advisories
    advisories = data.get('advisories', {})
    if isinstance(advisories, dict):
        for package, package_advisories in advisories.items():
            for advisory in package_advisories:
                title = advisory.get('title', 'Security Vulnerability')
                cve = advisory.get('cve', 'Unknown CVE')
                link = advisory.get('link', '')
                affected = advisory.get('affectedVersions', '')
                advisory_id = advisory.get('advisoryId', cve)
                cwe = advisory.get('cwe') # Might be None

                # Create Rule if not exists
                if advisory_id not in rule_ids:
                    rule = {
                        "id": advisory_id,
                        "shortDescription": {
                            "text": f"{title} ({cve})"
                        },
                        "fullDescription": {
                            "text": f"Package: {package}\nCVE: {cve}\nAffected Versions: {affected}\nLink: {link}"
                        },
                        "helpUri": link
                    }
                    if cwe:
                         rule["properties"] = {
                            "cwe": [cwe]
                         }
                    
                    rules.append(rule)
                    rule_ids.add(advisory_id)
                
                # Create Result
                message = f"Security Vulnerability in {package}: {title} ({cve}). Affected: {affected}."
                
                results.append({
                    "ruleId": advisory_id,
                    "level": "error",
                    "message": {
                        "text": message
                    },
                    "locations": [
                        {
                            "physicalLocation": {
                                "artifactLocation": {
                                    "uri": "composer.lock"
                                },
                                "region": {
                                    "startLine": 1,
                                    "startColumn": 1
                                }
                            }
                        }
                    ]
                })

    # Handle abandoned packages
    abandoned = data.get('abandoned', {})
    if isinstance(abandoned, dict):
        for package, replacement in abandoned.items():
            rule_id = "abandoned-package"
            
            if rule_id not in rule_ids:
                 rules.append({
                    "id": rule_id,
                    "shortDescription": {
                        "text": "Abandoned Package"
                    },
                    "fullDescription": {
                        "text": "The package is abandoned and no longer maintained."
                    }
                 })
                 rule_ids.add(rule_id)

            message = f"Package {package} is abandoned."
            if replacement:
                message += f" Use {replacement} instead."
            
            results.append({
                "ruleId": rule_id,
                "level": "warning",
                "message": {
                    "text": message
                },
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {
                                "uri": "composer.lock"
                            },
                            "region": {
                                "startLine": 1,
                                "startColumn": 1
                            }
                        }
                    }
                ]
            })

    sarif_output = {
        "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "Composer Audit",
                        "informationUri": "https://getcomposer.org/doc/03-cli.md#audit",
                        "rules": rules
                    }
                },
                "results": results
            }
        ]
    }

    write_json(output_file, sarif_output)

def cli():
    if len(sys.argv) != 3:
        print("Usage: python3 composer_audit_to_sarif.py <input_json> <output_sarif>")
        sys.exit(1)
    
    convert_to_sarif(sys.argv[1], sys.argv[2])


if __name__ == "__main__":
    sys.exit(entry(cli))
