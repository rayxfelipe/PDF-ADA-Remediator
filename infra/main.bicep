targetScope = 'subscription'

@minLength(1)
@maxLength(64)
param environmentName string

@minLength(1)
param location string

@minLength(36)
@maxLength(36)
param sessionId string

@minLength(1)
param deployedBy string

param createdAt string

@minLength(36)
@maxLength(36)
param deployerObjectId string

@minLength(1)
param containerImageName string = 'pdf-ada-remediator:latest'

var tags = {
  'app-onboard-skill': 'true'
  'app-onboard-session-id': sessionId
  'created-at': createdAt
  environment: environmentName
  'deployed-by': deployedBy
}

resource resourceGroup 'Microsoft.Resources/resourceGroups@2024-11-01' = {
  name: 'rg-pdf-ada-staging-33f3'
  location: location
  tags: tags
}

module logAnalytics './modules/log-analytics.bicep' = {
  name: 'log-analytics'
  scope: resourceGroup
  params: {
    location: location
    name: 'log-pdf-ada-staging-33f3'
    tags: tags
  }
}

module applicationInsights './modules/application-insights.bicep' = {
  name: 'application-insights'
  scope: resourceGroup
  params: {
    location: location
    name: 'appi-pdf-ada-staging-33f3'
    tags: tags
    workspaceResourceId: logAnalytics.outputs.workspaceResourceId
  }
}

module containerRegistry './modules/container-registry.bicep' = {
  name: 'container-registry'
  scope: resourceGroup
  params: {
    location: location
    name: 'crpdfadastaging33f3'
    tags: tags
  }
}

module keyVault './modules/key-vault.bicep' = {
  name: 'key-vault'
  scope: resourceGroup
  params: {
    location: location
    name: 'kv-pdf-ada-staging-33f3'
    tags: tags
  }
}

module appService './modules/app-service.bicep' = {
  name: 'app-service'
  scope: resourceGroup
  params: {
    location: location
    planName: 'asp-pdf-ada-staging-33f3'
    appName: 'app-pdf-ada-staging-33f3'
    tags: tags
    containerImage: '${containerRegistry.outputs.loginServer}/${containerImageName}'
    applicationInsightsConnectionString: applicationInsights.outputs.connectionString
  }
}

module roleAssignments './modules/role-assignments.bicep' = {
  name: 'role-assignments'
  scope: resourceGroup
  params: {
    acrName: 'crpdfadastaging33f3'
    appPrincipalId: appService.outputs.principalId
    deployerObjectId: deployerObjectId
    keyVaultName: 'kv-pdf-ada-staging-33f3'
  }
  dependsOn: [
    keyVault
  ]
}

output appServiceName string = appService.outputs.appServiceName
output appServiceUrl string = appService.outputs.defaultHostName
output containerRegistryName string = containerRegistry.outputs.name
output keyVaultName string = keyVault.outputs.name
output resourceGroupName string = resourceGroup.name