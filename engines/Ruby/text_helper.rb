#!/usr/bin/env ruby

require 'json'
require 'net/http'
require 'uri'
require 'optparse'

class TextHelper
  def initialize(engine: nil)
    @engine = engine || detect_engine
    @openai_key = ENV['OPENAI_API_KEY']
    @lmstudio_key = ENV['LMSTUDIO_API_KEY']
    @lmstudio_base = ENV['LMSTUDIO_API_BASE'] || 'http://127.0.0.1:8080'
    @lmstudio_model = ENV['LMSTUDIO_MODEL']
  end

  def detect_engine
    return 'openai' if ENV['OPENAI_API_KEY'] && !ENV['OPENAI_API_KEY'].empty?
    return 'lmstudio' if ENV['LMSTUDIO_API_KEY'] && !ENV['LMSTUDIO_API_KEY'].empty?
    raise 'No engine configured. Set OPENAI_API_KEY or LMSTUDIO_API_KEY.'
  end

  def choose_model(task)
    return @lmstudio_model if @engine == 'lmstudio' && @lmstudio_model && !@lmstudio_model.empty?

    case task
    when :summarize, :key_points, :sentiment, :short
      @engine == 'openai' ? 'gpt-3.5-turbo' : 'llama2-1.7b-chat'
    when :analyze, :explain, :reason
      @engine == 'openai' ? 'gpt-4o-mini' : 'llama2-4b-chat'
    else
      @engine == 'openai' ? 'gpt-3.5-turbo' : 'llama2-1.7b-chat'
    end
  end

  def build_prompt(task, text)
    case task
    when :summarize
      "Summarize the following text clearly and concisely:\n\n#{text}"
    when :key_points
      "Extract the most important key points from the following text:\n\n#{text}"
    when :sentiment
      "Analyze the sentiment of the following text and describe tone, mood, and intent:\n\n#{text}"
    when :explain
      "Explain the meaning and context of the following text, including any implied conclusions or recommendations:\n\n#{text}"
    when :reason
      "Perform a reasoned analysis of the following text and provide insights or next steps as appropriate:\n\n#{text}"
    else
      "Process the following text as requested:\n\n#{text}"
    end
  end

  def request(task, text)
    model = choose_model(task)
    prompt = build_prompt(task, text)
    messages = [
      { role: 'system', content: 'You are a helpful assistant that summarizes, extracts key points, and analyzes sentiment.' },
      { role: 'user', content: prompt }
    ]

    case @engine
    when 'openai'
      openai_request(model, messages)
    when 'lmstudio'
      lmstudio_request(model, messages)
    else
      raise "Unsupported engine: #{@engine}"
    end
  end

  def openai_request(model, messages)
    uri = URI('https://api.openai.com/v1/chat/completions')
    req = Net::HTTP::Post.new(uri)
    req['Content-Type'] = 'application/json'
    req['Authorization'] = "Bearer #{@openai_key}"
    req.body = { model: model, messages: messages, temperature: 0.3 }.to_json

    http = Net::HTTP.new(uri.host, uri.port)
    http.use_ssl = true
    response = http.request(req)
    parse_response(response)
  end

  def lmstudio_request(model, messages)
    uri = URI(File.join(@lmstudio_base, '/v1/chat/completions'))
    req = Net::HTTP::Post.new(uri)
    req['Content-Type'] = 'application/json'
    req['Authorization'] = "Bearer #{@lmstudio_key}" if @lmstudio_key && !@lmstudio_key.empty?
    req.body = { model: model, messages: messages, temperature: 0.3 }.to_json

    http = Net::HTTP.new(uri.host, uri.port)
    http.use_ssl = uri.scheme == 'https'
    response = http.request(req)
    parse_response(response)
  end

  def parse_response(response)
    body = JSON.parse(response.body)
    if response.is_a?(Net::HTTPSuccess) && body['choices'] && body['choices'].any?
      body['choices'].first['message']['content'].strip
    else
      raise "API error: #{response.code} #{body.inspect}"
    end
  rescue JSON::ParserError
    raise "Invalid JSON response: #{response.body}"
  end

  def summarize(text)
    request(:summarize, text)
  end

  def key_points(text)
    request(:key_points, text)
  end

  def sentiment(text)
    request(:sentiment, text)
  end

  def explain(text)
    request(:explain, text)
  end

  def reason(text)
    request(:reason, text)
  end
end

def print_usage
  puts <<~USAGE
    Usage: ruby text_helper.rb [options] <command> <text>

    Commands:
      summarize   Summarize text
      key_points  Extract key points
      sentiment   Analyze sentiment
      explain     Explain meaning and context
      reason      Perform reasoned analysis

    Options:
      -e, --engine ENGINE   openai or lmstudio

    Environment variables:
      OPENAI_API_KEY      OpenAI API key
      LMSTUDIO_API_KEY    LM Studio API key
      LMSTUDIO_API_BASE   LM Studio base URL (default http://127.0.0.1:8080)
      LMSTUDIO_MODEL      LM Studio model name (default llama2-1.7b-chat for small tasks, llama2-4b-chat for analysis)
  USAGE
end

options = {}
parser = OptionParser.new do |opts|
  opts.on('-eENGINE', '--engine=ENGINE', 'Engine to use: openai or lmstudio') do |engine|
    options[:engine] = engine.downcase
  end
  opts.on('-h', '--help', 'Show this help message') do
    print_usage
    exit
  end
end

begin
  parser.order!
rescue OptionParser::InvalidOption => e
  puts e.message
  print_usage
  exit 1
end

command = ARGV.shift
text = ARGV.join(' ')

if command.nil? || text.strip.empty?
  print_usage
  exit 1
end

task = case command.downcase
       when 'summarize' then :summarize
       when 'key_points', 'keypoints', 'key-points' then :key_points
       when 'sentiment' then :sentiment
       when 'explain' then :explain
       when 'reason' then :reason
       else
         puts "Unknown command: #{command}"
         print_usage
         exit 1
       end

helper = TextHelper.new(engine: options[:engine])
puts helper.send(task, text)
