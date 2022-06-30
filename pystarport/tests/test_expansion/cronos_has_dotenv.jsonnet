local config = import './cronos_has_posix_no_dotenv.jsonnet';

config {
  dotenv+: 'dotenv',
}
