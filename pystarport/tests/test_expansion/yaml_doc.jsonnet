// jsonnet yaml_doc.jsonnet -m . -S
{
  'base.yaml': std.manifestYamlDoc(import './base.jsonnet', true, false),
  'cronos_has_dotenv.yaml': std.manifestYamlDoc(import './cronos_has_dotenv.jsonnet', true, false),
  'cronos_has_posix_no_dotenv.yaml': std.manifestYamlDoc(import './cronos_has_posix_no_dotenv.jsonnet', true, false),
  'cronos_no_dotenv.yaml': std.manifestYamlDoc(import './cronos_no_dotenv.jsonnet', true, false),
}
