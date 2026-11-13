# frozen_string_literal: true

# Configure iD only in the disposable Rails source copy, using its synthetic
# OAuth application. Never copy a live OAuth UID or secret into this file.
unless ENV["BRAZIL_STAGE_ONLY"] == "I_APPROVE_DISPOSABLE_STAGE" &&
       ENV.fetch("DATABASE_URL", "") == "postgresql://openstreetmap@db/openstreetmap"
  abort "refusing to configure iD outside the disposable stage"
end

app = Oauth2Application.find_by!(:name => "Brazil isolated edit rehearsal")
path = "/app/config/settings.local.yml"
File.write(path, "id_application: #{app.uid.inspect}\n")
File.chmod(0o600, path)
puts "disposable iD OAuth application configured"
