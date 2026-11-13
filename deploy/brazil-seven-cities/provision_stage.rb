# frozen_string_literal: true

# Run with `bundle exec rails runner tmp/provision_brazil_stage.rb` only inside a
# freshly verified disposable Rails project. Output stays in that private copy.
require "securerandom"

unless ENV["BRAZIL_STAGE_ONLY"] == "I_APPROVE_DISPOSABLE_STAGE" &&
       ENV.fetch("DATABASE_URL", "") == "postgresql://openstreetmap@db/openstreetmap"
  abort "refusing to provision outside the disposable stage"
end

run_id = ENV.fetch("BRAZIL_STAGE_RUN_ID")
abort "unsafe run ID" unless run_id.match?(/\A[0-9]{8}-[0-9a-f]{8}\z/)
output = "/app/tmp/brazil-stage-#{run_id}.env"
abort "credential file already exists" if File.exist?(output)

password = SecureRandom.hex(24)
now = Time.current
user = User.new(:display_name => "BrazilStage#{run_id.delete('-')}",
                :email => "brazil-stage-#{run_id}@example.invalid",
                :pass_crypt => password, :pass_crypt_confirmation => password,
                :data_public => true, :email_valid => true,
                :creation_time => now, :terms_agreed => now, :tou_agreed => now,
                :terms_seen => true)
user.save!
user.activate!
app = Oauth2Application.create!(:owner => user,
                                 :name => "Brazil isolated edit rehearsal",
                                 :redirect_uri => "http://127.0.0.1:39003/",
                                 :scopes => "read_prefs write_api",
                                 :confidential => false)
token = Doorkeeper::AccessToken.create!(:application_id => app.id,
                                         :resource_owner_id => user.id,
                                         :scopes => "read_prefs write_api",
                                         :expires_in => 3600)
File.open(output, File::WRONLY | File::CREAT | File::EXCL, 0o600) do |file|
  file.write("OSM_API_TOKEN=#{token.token}\n")
  file.write("OSM_API_ACCOUNT=#{user.display_name}\n")
  file.write("STAGE_LOGIN_PASSWORD=#{password}\n")
end
puts "synthetic stage user and scoped OAuth token provisioned"
